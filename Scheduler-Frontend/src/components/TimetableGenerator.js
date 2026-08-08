import React, { useState } from 'react';
import Header from './Header';
import FileUpload from './FileUpload';
import TimetableResults from './TimetableResults';
import InstructionsModal from './InstructionsModal';
import { uploadFile, generateTimetable, downloadTimetable } from '../services/api';
import './TimetableGenerator.css';

const TimetableGenerator = () => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadId, setUploadId] = useState(null); // Track upload ID for downloads
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState('');
  const [generatedData, setGeneratedData] = useState([]);
  const [showInstructions, setShowInstructions] = useState(false);
  const [error, setError] = useState('');

  const [generations, setGenerations] = useState('');

  const handleFileSelect = (file) => {
    console.log('File selected:', file);
    setSelectedFile(file);
    setError('');
    setGeneratedData([]);
    setUploadId(null); // Reset upload ID
    setGenerations('');
    // Generations selector intentionally not auto-shown (disabled)
  };

  const handleFileReset = () => {
    console.log('Resetting file selection');
    setSelectedFile(null);
    setUploadId(null);
    setIsProcessing(false);
    setProgress(0);
    setProgressText('');
    setGeneratedData([]);
    setError('');
    setGenerations('');
  };

  const startGeneration = async (currentUploadId) => {
    // Start generation with progress updates and user-provided generations
    setProgress(30);
    setProgressText('Starting timetable generation...');

    const progressCallback = (progressData) => {
      console.log('Progress update:', progressData);
      if (!progressData) return;
      const pct = typeof progressData.percentage === 'number' ? progressData.percentage : null;
      if (pct !== null) {
        // Allow progress to reach 100 when backend reports completion
        const clampedProgress = Math.min(Math.max(pct, 30), 100);
        setProgress(clampedProgress);
      }
      if (progressData.message) {
        setProgressText(progressData.message);
      }
    };

    // Build options: require generations
    const gens = parseInt(generations, 10);
    const options = Number.isFinite(gens) && gens > 0 ? { max_generations: gens } : {};

    // Generate timetable using the upload ID with options
    console.log('Generating timetable with ID:', currentUploadId, 'options:', options);
    const timetableData = await generateTimetable(currentUploadId, progressCallback, options);
    console.log('Timetable generation completed:', timetableData);

    // Extract timetables from response - handle different response formats
    // PRIORITIZE timetables_raw which contains the actual grid data (rows),
    // whereas 'timetables' usually contains just the summary cards.
    let timetables = [];
    if (timetableData) {
      timetables =
        timetableData.timetables_raw ||
        timetableData.data?.timetables_raw ||
        timetableData.timetables ||
        timetableData.data?.timetables ||
        timetableData.results ||
        (Array.isArray(timetableData) ? timetableData : []);
    }

    console.log('Extracted timetables:', timetables);

    if (!Array.isArray(timetables)) {
      console.warn('Timetables is not an array, converting:', timetables);
      timetables = timetables ? [timetables] : [];
    }

    setProgress(100);
    setProgressText('Complete!');
    setGeneratedData(timetables);

    setTimeout(() => {
      setIsProcessing(false);
      setProgress(0);
      setProgressText('');
    }, 1500);
  };

  const handleGenerate = async () => {
    if (!selectedFile || isProcessing) {
      console.log('Cannot generate: no file selected or already processing');
      return;
    }

    // Generations selector is disabled; use backend defaults unless user supplies options

    if (!uploadId) {
      // Perform upload first, then immediately start generation
      console.log('Starting upload then generation...');
      setIsProcessing(true);
      setError('');
      setGeneratedData([]);
      setProgress(5);
      setProgressText('Preparing upload...');

      try {
        setProgress(10);
        setProgressText('Uploading file...');
        console.log('Uploading file:', selectedFile.name);

        const uploadResponse = await uploadFile(selectedFile);
        console.log('Upload response:', uploadResponse);

        const currentUploadId =
          uploadResponse?.uploadId ||
          uploadResponse?.upload_id ||
          uploadResponse?.fileId ||
          uploadResponse?.id ||
          (uploadResponse?.meta && (
            uploadResponse.meta.upload_id ||
            uploadResponse.meta.uploadId ||
            uploadResponse.meta.id
          ));

        console.log('Extracted upload ID:', currentUploadId);

        if (!currentUploadId) {
          throw new Error('Upload ID not returned by server. Response: ' + JSON.stringify(uploadResponse));
        }

        setUploadId(currentUploadId);
        await startGeneration(currentUploadId);
        return;
      } catch (err) {
        console.error('Timetable generation error:', err);
        let errorMessage = 'An error occurred while generating the timetable';
        if (err?.response?.data?.error) {
          errorMessage = err.response.data.error;
        } else if (err?.response?.data?.message) {
          errorMessage = err.response.data.message;
        } else if (err?.message) {
          errorMessage = err.message;
        }
        setError(errorMessage);
        setIsProcessing(false);
        setProgress(0);
        setProgressText('');
        return;
      }
    }

    try {
      setIsProcessing(true);
      await startGeneration(uploadId);
    } catch (err) {
      console.error('Timetable generation error:', err);
      let errorMessage = 'An error occurred while generating the timetable';
      if (err?.response?.data?.error) {
        errorMessage = err.response.data.error;
      } else if (err?.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err?.message) {
        errorMessage = err.message;
      }
      setError(errorMessage);
      setIsProcessing(false);
      setProgress(0);
      setProgressText('');
    }
  };

  const handleDownload = async (format) => {
    if (!uploadId) {
      setError('No timetable data available for download - missing upload ID');
      return;
    }

    if (generatedData.length === 0) {
      setError('No timetable data available for download - no generated data');
      return;
    }

    console.log(`Starting download: ${format} format for upload ID: ${uploadId}`);

    try {
      await downloadTimetable(uploadId, format);
      console.log('Download completed successfully');
    } catch (err) {
      console.error('Download error:', err);
      let errorMessage = 'An error occurred while downloading';
      if (err?.response?.data?.error) {
        errorMessage = err.response.data.error;
      } else if (err?.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err?.message) {
        errorMessage = err.message;
      }
      setError(errorMessage);
    }
  };

  console.log('Rendering TimetableGenerator component', handleDownload);

  // Debug log for component state
  console.log('TimetableGenerator state:', {
    selectedFile: selectedFile?.name,
    uploadId,
    isProcessing,
    progress,
    generatedDataLength: generatedData.length,
    error
  });

  return (
    <div className="timetable-generator">
      <Header
        onShowInstructions={() => setShowInstructions(true)}
      />

      <main className="main-container">
        <FileUpload
          selectedFile={selectedFile}
          onFileSelect={handleFileSelect}
          onFileReset={handleFileReset}
          onGenerate={handleGenerate}
          isProcessing={isProcessing}
          progress={progress}
          progressText={progressText}
          error={error}
          disableGenerate={isProcessing}
          showGenerationsSelector={false}
          generations={generations}
          onGenerationsChange={(val) => setGenerations(val)}
        />

        {uploadId && !isProcessing && generatedData.length > 0 && (
          <>
            <TimetableResults
              result={{ timetables: generatedData }}
              uploadId={uploadId}
            />
          </>
        )}

        {error && (
          <div className="error-message" style={{ 
            color: '#dc3545', 
            backgroundColor: '#f8d7da',
            border: '1px solid #f5c6cb',
            borderRadius: '4px',
            padding: '12px',
            marginTop: '16px',
            fontSize: '14px'
          }}>
            <strong>Error:</strong> {error}
          </div>
        )}
      </main>

      <InstructionsModal
        isOpen={showInstructions}
        onClose={() => setShowInstructions(false)}
      />
    </div>
  );
};

export default TimetableGenerator;