// Mock axios so CRA/Jest doesn't need to parse axios's ESM bundle.
// We only rely on axios.create() returning a client with interceptors.
const mockCreate = jest.fn();
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: mockCreate,
  },
}));

// Mock environment variables
const originalEnv = process.env;

beforeEach(() => {
  jest.resetModules();
  process.env = {
    ...originalEnv,
    REACT_APP_API_BASE_URL: 'http://localhost:8000/api',
    REACT_APP_UPLOAD_ENDPOINT: '/timetable/upload',
    // generateTimetable() uses '/generate-timetable' in current API service
    // downloadTimetable() uses '/export-timetable'
  };

  // Provide a fresh mock client per test; apiClient is created at module import time.
  const mockClient = {
    post: jest.fn(),
    get: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    }
  };

  mockCreate.mockReturnValue(mockClient);

  // Expose for tests
  global.__mockApiClient = mockClient;
});

afterEach(() => {
  process.env = originalEnv;
  jest.clearAllMocks();
});

describe('API Service', () => {
  describe('uploadFile', () => {
    test('successfully uploads file', async () => {
      const { uploadFile } = require('../api');
      const apiClient = global.__mockApiClient;

      const mockResponse = {
        data: {
          upload_id: 'test-file-id',
          filename: 'test.xlsx',
          status: 'uploaded'
        }
      };

      apiClient.post.mockResolvedValue(mockResponse);
      
      const file = new File(['test content'], 'test.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      
      const result = await uploadFile(file);
      
      expect(apiClient.post).toHaveBeenCalledWith('/timetable/upload', expect.any(FormData));
      expect(result).toEqual({ uploadId: 'test-file-id', meta: mockResponse.data });
    });

    test('handles upload error', async () => {
      const { uploadFile } = require('../api');
      const apiClient = global.__mockApiClient;

      const error = new Error('Network Error');
      apiClient.post.mockRejectedValue(error);
      
      const file = new File(['test'], 'test.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      
      await expect(uploadFile(file)).rejects.toThrow('File upload failed: Network Error');
    });
  });

  describe('generateTimetable', () => {
    test('successfully generates timetable', async () => {
      const { generateTimetable } = require('../api');
      const apiClient = global.__mockApiClient;

      const mockResponse = {
        status: 202,
        data: { message: 'started' }
      };

      apiClient.post.mockResolvedValue(mockResponse);
      apiClient.get.mockResolvedValueOnce({
        data: {
          status: 'completed',
          progress: 100,
          result: { timetables: [] }
        }
      });
      
      const result = await generateTimetable('test-file-id');
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/generate-timetable',
        expect.objectContaining({
          upload_id: 'test-file-id',
          config: expect.any(Object)
        })
      );
      expect(apiClient.get).toHaveBeenCalledWith('/get-timetable-status/test-file-id');
      expect(result).toEqual({ timetables: [] });
    });

    test('calls progress callback', async () => {
      const { generateTimetable } = require('../api');
      const apiClient = global.__mockApiClient;

      const mockResponse = { status: 202, data: { message: 'started' } };
      const progressCallback = jest.fn();

      apiClient.post.mockResolvedValue(mockResponse);
      apiClient.get.mockResolvedValueOnce({
        data: {
          status: 'completed',
          progress: 100,
          message: 'done',
          result: { timetables: [] }
        }
      });
      
      await generateTimetable('test-file-id', progressCallback);

      expect(progressCallback).toHaveBeenCalled();
    });

    test('handles generation error', async () => {
      const { generateTimetable } = require('../api');
      const apiClient = global.__mockApiClient;

      const error = new Error('Generation failed');
      apiClient.post.mockRejectedValue(error);
      
      await expect(generateTimetable('test-file-id')).rejects.toThrow('Timetable generation failed: Generation failed');
    });
  });

  describe('downloadTimetable', () => {
    test('successfully downloads timetable', async () => {
      const { downloadTimetable } = require('../api');
      const apiClient = global.__mockApiClient;

      const mockBlob = new Blob(['test content'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const mockResponse = { data: mockBlob };
      
      apiClient.post.mockResolvedValue(mockResponse);
      
      // Mock DOM methods
      const mockLink = {
        href: '',
        setAttribute: jest.fn(),
        click: jest.fn(),
        remove: jest.fn()
      };
      
      document.createElement = jest.fn().mockReturnValue(mockLink);
      document.body.appendChild = jest.fn();
      window.URL.createObjectURL = jest.fn().mockReturnValue('blob:test-url');
      window.URL.revokeObjectURL = jest.fn();

      await downloadTimetable('test-file-id', 'excel');
      
      expect(apiClient.post).toHaveBeenCalledWith(
        '/export-timetable',
        expect.objectContaining({
          upload_id: 'test-file-id',
          format: 'excel'
        }),
        expect.objectContaining({ responseType: 'blob' })
      );
      
      expect(document.createElement).toHaveBeenCalledWith('a');
      expect(mockLink.click).toHaveBeenCalled();
      expect(window.URL.revokeObjectURL).toHaveBeenCalled();
    });

    test('handles download error', async () => {
      const { downloadTimetable } = require('../api');
      const apiClient = global.__mockApiClient;

      const error = new Error('Download failed');
      apiClient.post.mockRejectedValue(error);

      await expect(downloadTimetable('test-file-id', 'excel')).rejects.toThrow('Download failed: Download failed');
    });
  });
});