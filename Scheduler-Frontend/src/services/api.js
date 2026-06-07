// Use the public axios entrypoint for the app build (respects package.json exports).
// Unit tests mock this module to avoid Jest ESM parsing issues.
import axios from 'axios';

// Determine API base URL based on environment
const getApiBaseUrl = () => {
  // For development, use relative URLs to work with proxy
  if (process.env.NODE_ENV === 'development') {
    return '';
  }
  
  // Custom API Base URL override
  if (process.env.REACT_APP_API_BASE_URL) return process.env.REACT_APP_API_BASE_URL;
  
  // Fallback to the known Hugging Face Space URL for production
  // Note: https://huggingface.co/spaces/PAU-001/PAU-Timetable-Scheduler is the REPO view.
  // The API runs at the .hf.space subdomain:
  return 'https://pau-001-pau-timetable-scheduler.hf.space';
};

const API_BASE_URL = getApiBaseUrl();
console.log('🔗 API Base URL configured to:', API_BASE_URL || 'Relative URL (Proxy)');


// Create axios instance with CORS-friendly config
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 0, // No timeout (infinite)
  withCredentials: false, // Important for CORS
  headers: {
    'Accept': 'application/json',
    // Content-Type set conditionally in interceptor
  },
});

// Add request interceptor for logging and proper headers
apiClient.interceptors.request.use(
  (config) => {
    const method = (config.method || 'GET').toUpperCase();
    const url = config.baseURL ? `${config.baseURL}${config.url}` : config.url;
    console.log(`Making ${method} request to ${url}`);

    // Set appropriate headers for different request types
    if (config.data instanceof FormData) {
      // For file uploads, let browser set Content-Type with boundary
      if (config.headers) {
        delete config.headers['Content-Type'];
      }
    } else if (typeof config.data === 'object' && config.data !== null) {
      // For JSON data
      if (config.headers) {
        config.headers['Content-Type'] = 'application/json';
      }
    }

    // Do NOT set Access-Control-Allow-* on requests (these are response headers)
    return config;
  },
  (error) => {
    console.error('Request error:', error);
    return Promise.reject(error);
  }
);

// Add response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);

    // Distinguish unreachable backend vs actual CORS rejection
    if (error.request && !error.response) {
      // Network error / connection refused
      if (error.code === 'ERR_NETWORK' || (error.message && error.message.includes('Network Error'))) {
        throw new Error('Cannot reach backend server. Ensure it is running and the API base URL is correct.');
      }
    }

    if (error.response) {
      const { status, data } = error.response;

      // Some browsers report CORS failures with opaque responses (status 0)
      if (status === 0) {
        throw new Error('CORS error: Backend did not allow this origin.');
      }

      let message;
      if (status === 504) {
        message = 'Server timeout (504): backend did not respond in time. Try again or check server logs.';
      } else {
        message = data?.message || data?.error || `Server error (${status})`;
      }
      throw new Error(message);
    }

    // Fallback
    throw new Error(error.message || 'An unexpected error occurred');
  }
);

/**
 * Make a CORS-safe request with retry logic
 * @param {Function} requestFn - The axios request function
 * @param {number} retries - Number of retries
 */
const makeRequestWithRetry = async (requestFn, retries = 3) => {
  for (let i = 0; i < retries; i++) {
    try {
      return await requestFn();
    } catch (error) {
      if (i === retries - 1) throw error;

      const msg = (error && (error.message || (error.response && error.response.data && (error.response.data.error || error.response.data.message)))) || '';
      // If temporary network/CORS-like error or HTTP 504, wait and retry
      const isTransient = (msg && (msg.toString().toLowerCase().includes('cors') || msg.toString().toLowerCase().includes('backend') || msg.toString().toLowerCase().includes('network') || msg.toString().includes('504')))
        || (error && error.response && error.response.status === 504);

      if (isTransient) {
        console.log(`Temporary connectivity/error condition, retrying... (${i + 1}/${retries})`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
      } else {
        throw error;
      }
    }
  }
};

/**
 * Upload file to the server with CORS handling
 * @param {File} file - The Excel file to upload
 * @returns {Promise<Object>} Response containing file ID and metadata
 */
export const uploadFile = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('filename', file.name);

  const uploadEndpoint = process.env.REACT_APP_UPLOAD_ENDPOINT || '/upload-excel';

  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.post(uploadEndpoint, formData)
    );

    const data = response.data;
    const uploadId = data.upload_id || data.uploadId || data.id; // defensive read
    if (!uploadId) throw new Error('upload_id not returned by server');

    console.log('Upload successful:', data);
    return { uploadId, meta: data };
  } catch (err) {
    console.error('Upload error details:', err);
    const message = err?.response?.data?.error || err.message || 'Upload failed';
    throw new Error(`File upload failed: ${message}`);
  }
};

/**
 * Generate timetable from uploaded file
 * @param {string} uploadId - ID of the uploaded file
 * @param {Function} progressCallback - Callback for progress updates
 * @param {Object} options - Optional parameters to override defaults (e.g., max_generations)
 * @returns {Promise<Object>} Generated timetable data
 */
export const generateTimetable = async (uploadId, progressCallback, options) => {
  try {
    // Start the generation process
    const body = {
      upload_id: uploadId,
      config: {
        population_size: Number(process.env.REACT_APP_DE_POP_SIZE) || 1,
        max_generations: Number(process.env.REACT_APP_DE_MAX_GENS) || 20,
        F: Number(process.env.REACT_APP_DE_F) || 0.4,
        CR: Number(process.env.REACT_APP_DE_CR) || 0.9,
        solver_mode: 'hybrid',
        cpsat_enforce_workload: true,
        cpsat_soft_optimize: true,
        cpsat_time_limit_seconds: Number(process.env.REACT_APP_CPSAT_TIME_LIMIT) || 450,
        cpsat_soft_time_limit_seconds: Number(process.env.REACT_APP_CPSAT_SOFT_TIME_LIMIT) || 450
      }
    };

    // Allow overrides from caller (e.g., user-provided generations)
    if (options && typeof options === 'object') {
      body.config = { ...body.config, ...options };
    }

    console.log('Starting timetable generation with:', body);
    const startResponse = await makeRequestWithRetry(() =>
      apiClient.post('/generate-timetable', body)
    );

    if (startResponse.status !== 202) {
      throw new Error('Failed to start timetable generation');
    }

    console.log('Generation started, polling for status...');
    // Poll for status updates
    return await pollForCompletion(uploadId, progressCallback);

  } catch (error) {
    console.error('Generation error:', error);
    const msg = error?.response?.data?.error || error?.message || 'Unknown error';
    throw new Error(`Timetable generation failed: ${msg}`);
  }
};

/**
 * Poll the server for generation completion status with CORS handling
 * @param {string} uploadId - Upload ID to check status for
 * @param {Function} progressCallback - Progress update callback
 * @returns {Promise<Object>} Final timetable data
 */
const pollForCompletion = async (uploadId, progressCallback) => {
  const maxAttempts = 3000; // ~4 hours with 5-second intervals
  let attempts = 0;

  return new Promise((resolve, reject) => {
    const checkStatus = async () => {
      try {
        attempts++;
        const statusResponse = await makeRequestWithRetry(() =>
          apiClient.get(`/get-timetable-status/${uploadId}`)
        );
        const statusData = statusResponse && statusResponse.data ? statusResponse.data : {};

        // Normalize status and derive sensible defaults
        const normalized = {
          status: statusData.status || statusData.State || statusData.state,
          progress: typeof statusData.progress === 'number' ? statusData.progress : 0,
          message: statusData.message || '',
          result: statusData.result,
          error: statusData.error || statusData.Error
        };

        // If backend returned a completed result but no explicit status
        if (!normalized.status && normalized.result) {
          normalized.status = 'completed';
        }
        // If backend indicates error but no explicit status
        if (!normalized.status && normalized.error) {
          normalized.status = 'error';
        }
        // Default to processing if still undefined but HTTP 200
        if (!normalized.status) {
          normalized.status = 'processing';
        }

        // Update progress UI
        if (progressCallback) {
          progressCallback({
            percentage: normalized.progress,
            message: normalized.message || 'Processing...'
          });
        }

        if (normalized.status === 'completed') {
          const result = normalized.result;
          if (result) {
            // Prefer grid rows for the interactive timetable (same as TimetableGenerator).
            if (result.timetables_raw) {
              result.timetables = result.timetables_raw;
            }
            if (result.parsed_timetables && result.timetables) {
              result.timetables = result.timetables.map((timetable, index) => {
                const parsed = result.parsed_timetables[index];
                return { ...timetable, rows: parsed ? parsed.rows : [] };
              });
            }
          }
          // ensure UI reflects completion
          if (progressCallback) {
            progressCallback({ percentage: 100, message: 'Completed' });
          }
          resolve(result);
          return;
        }

        if (normalized.status === 'error') {
          reject(new Error(normalized.error || 'Generation failed'));
          return;
        }

        // Still processing, continue polling
        if (attempts >= maxAttempts) {
          reject(new Error('Generation timeout - please try again'));
          return;
        }
        setTimeout(checkStatus, 5000);
        return;
      } catch (error) {
        console.error('Status check error:', error);
        if (error.message.includes('CORS')) {
          reject(new Error('CORS policy is blocking requests to the backend. Please check the server configuration.'));
        } else {
          reject(error);
        }
      }
    };

    // Start polling
    checkStatus();
  });
};

/**
 * Download generated timetable in specified format with CORS handling
 * @param {string} uploadId - The upload ID from the generation process
 * @param {string} format - Download format ('excel', 'pdf')
 * @returns {Promise<void>}
 */
export const downloadTimetable = async (uploadId, format) => {
  try {
    console.log(`Downloading timetable: ${uploadId} in ${format} format`);
    const response = await makeRequestWithRetry(() =>
      apiClient.post(
        '/export-timetable',
        {
          upload_id: uploadId,
          format: format.toLowerCase()
        },
        {
          responseType: 'blob', // Important for file downloads
        }
      )
    );

    // Create blob link to download
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    
    // Set filename based on format
    const timestamp = new Date().toISOString().slice(0, 10);
    const filename = `timetable_${timestamp}.${format === 'pdf' ? 'pdf' : 'xlsx'}`;
    link.setAttribute('download', filename);
    
    // Trigger download
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    
  } catch (error) {
    console.error('Download error:', error);
    throw new Error(`Download failed: ${error.message}`);
  }
};

/**
 * Get available time slots from server
 * @returns {Promise<Array>} Available time slots
 */
export const getTimeSlots = async () => {
  try {
    // Try to get time slots from API first
    const response = await makeRequestWithRetry(() =>
      apiClient.get('/timetable/timeslots')
    );
    return response.data;
  } catch (error) {
    // If API endpoint doesn't exist or fails, return default time slots
    console.warn('Failed to fetch time slots from API, using defaults:', error.message);
    return [
      { start: '08:30', end: '09:30', label: '8:30 AM' },
      { start: '09:30', end: '10:30', label: '9:30 AM' },
      { start: '10:30', end: '11:30', label: '10:30 AM' },
      { start: '11:30', end: '12:30', label: '11:30 AM' },
      // Break usually at 12:30-13:30
      { start: '13:30', end: '14:30', label: '1:30 PM' },
      { start: '14:30', end: '15:30', label: '2:30 PM' },
      { start: '15:30', end: '16:30', label: '3:30 PM' },
      { start: '16:30', end: '17:30', label: '4:30 PM' },
      { start: '17:30', end: '18:30', label: '5:30 PM' },
    ];
  }
};

/**
 * Validate uploaded file on server
 * @param {string} fileId - ID of uploaded file
 * @returns {Promise<Object>} Validation results
 */
export const validateFile = async (fileId) => {
  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.post('/timetable/validate', { fileId })
    );
    return response.data;
  } catch (error) {
    throw new Error(`File validation failed: ${error.message}`);
  }
};

/**
 * Utilities to work with the backend Dash UI mounted under /interactive
 */
export const getBackendBaseUrl = () => API_BASE_URL;

// Dash UI is now disabled - all UI handled by React frontend
export const getDashUrl = (uploadId) => {
  // This endpoint no longer exists - frontend handles all UI
  return null;
};

export const openDashUI = (uploadId) => {
  // Dash UI is disabled - no action needed
  console.warn('Dash UI has been disabled. All timetable UI is now in React.');
};

/**
 * Get rooms data for room selection
 * @returns {Promise<Array>} Array of room objects
 */
export const getRoomsData = async () => {
  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.get('/api/get-rooms-data')
    );
    return response.data.rooms || [];
  } catch (error) {
    console.error('Error fetching rooms data:', error);
    return [];
  }
};

/**
 * Get constraint violations for a timetable
 * @param {string} uploadId - Upload ID
 * @returns {Promise<Object>} Constraint violations object
 */
export const getConstraintViolations = async (uploadId) => {
  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.get(`/api/get-constraint-violations/${uploadId}`)
    );
    return response.data.violations || {};
  } catch (error) {
    console.error('Error fetching constraint violations:', error);
    return {};
  }
};

/**
 * Get mapping of course code -> lecturer options for a given upload.
 * Used to mark multi-lecturer courses and allow switching the primary lecturer.
 */
export const getCourseLecturers = async (uploadId) => {
  try {
    if (!uploadId) return {};
    const response = await makeRequestWithRetry(() =>
      apiClient.get(`/api/get-course-lecturers/${uploadId}`)
    );
    return response.data.course_lecturers || {};
  } catch (error) {
    console.error('Error fetching course lecturers:', error);
    return {};
  }
};

/**
 * Save timetable changes with manual modifications
 * @param {Object} data - Timetable data with manual_cells
 * @returns {Promise<Object>} Save response
 */
export const saveTimetableChanges = async (data) => {
  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.post('/api/save-timetable-changes', data)
    );
    return response.data;
  } catch (error) {
    console.error('Error saving timetable changes:', error);
    throw error;
  }
};

/**
 * Get previously saved timetable with manual changes
 * @param {string} uploadId - Upload ID
 * @returns {Promise<Object>} Saved timetable data
 */
export const getSavedTimetable = async (uploadId) => {
  try {
    const response = await makeRequestWithRetry(() =>
      apiClient.get(`/api/get-saved-timetable/${uploadId}`)
    );
    return response.data;
  } catch (error) {
    console.error('Error fetching saved timetable:', error);
    return { timetables: null, manual_cells: [] };
  }
};

export default apiClient;
