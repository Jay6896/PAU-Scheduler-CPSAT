import React, { useRef, useState } from 'react';
import './FileUpload.css';

const FileUpload = ({
  selectedFile,
  onFileSelect,
  onFileReset,
  onGenerate,
  isProcessing,
  progress,
  progressText,
  error,
  // New optional props to control enable/disable of generate button and show select
  disableGenerate,
  showGenerationsSelector,
  generations,
  onGenerationsChange
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const handleCancel = () => {
    // Allow re-selecting the same file after cancel.
    // Without clearing, browsers won't fire onChange for the same file path.
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    onFileReset && onFileReset();
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (file && validateFile(file)) {
      onFileSelect(file);
    }
  };

  const handleDragOver = (event) => {
    event.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setIsDragOver(false);
    
    const files = event.dataTransfer.files;
    if (files.length > 0 && validateFile(files[0])) {
      onFileSelect(files[0]);
    }
  };

  const validateFile = (file) => {
    const allowedTypes = process.env.REACT_APP_ALLOWED_FILE_TYPES?.split(',') || ['.xlsx', '.xls'];
    const maxSize = parseInt(process.env.REACT_APP_MAX_FILE_SIZE) || 10485760; // 10MB

    const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!allowedTypes.includes(fileExtension)) {
      alert('Please select a valid Excel file (.xlsx or .xls)');
      return false;
    }

    if (file.size > maxSize) {
      alert('File size must be less than 10MB');
      return false;
    }

    return true;
  };

  const formatFileSize = (bytes) => {
    return (bytes / 1024).toFixed(1);
  };

  return (
    <section 
      className={`upload-section ${isDragOver ? 'dragover' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="upload-header">
        <div className="upload-header-left">
          <div className="upload-icon">📁</div>
          <h3 className="upload-title">File Upload & Processing</h3>
        </div>
        
        {isProcessing && (
          <div className="progress-inline visible">
            <div className="progress-icon-inline">⟳</div>
            <div className="progress-bar-inline">
              <div 
                className="progress-fill-inline" 
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="progress-text">{progress}%</div>
          </div>
        )}
      </div>
      
      <div className="upload-content">
        <div className="upload-left">
          <div className="file-input-group">
            <input 
              type="text" 
              className="file-input-field" 
              placeholder="No file selected..." 
              value={selectedFile ? selectedFile.name : ''}
              readOnly 
            />
            <label htmlFor="fileInput" className="file-label">
              <span>📂</span> Browse...
            </label>
            <input 
              ref={fileInputRef}
              type="file" 
              id="fileInput" 
              className="file-input" 
              aria-label="Browse..."
              accept={process.env.REACT_APP_ALLOWED_FILE_TYPES || '.xlsx,.xls'}
              onChange={handleFileChange}
            />
          </div>
          
          {selectedFile && (
            <div className="selected-file">
              <strong>✓ File loaded:</strong> {selectedFile.name} ({formatFileSize(selectedFile.size)} KB)
            </div>
          )}

          {error && (
            <div className="error-message">
              <strong>❌ Error:</strong> {error}
            </div>
          )}

          {progressText && isProcessing && (
            <div className="progress-status">
              {progressText}
            </div>
          )}
          
          {selectedFile && (
            <div className="action-buttons visible">
              {/* Generations selector to the left of Generate button */}
              {/* Generations selector disabled per user request. To re-enable, restore the block below.
              {showGenerationsSelector && (
                <select
                  className="generations-select"
                  value={generations || ''}
                  onChange={(e) => onGenerationsChange && onGenerationsChange(e.target.value)}
                >
                  <option value="" disabled>Generations</option>
                  <option value="1">1</option>
                  <option value="5">5</option>
                  <option value="10">10</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                </select>
              )}
              */}

              <button 
                className="generate-btn" 
                onClick={onGenerate}
                disabled={isProcessing || disableGenerate}
                type="button"
              >
                <span className="btn-icon">
                  {isProcessing ? '⟳' : '▶'}
                </span>
                {isProcessing ? 'Processing...' : 'Generate Timetable'}
              </button>
              <button 
                className="cancel-btn" 
                onClick={handleCancel}
                disabled={isProcessing}
                type="button"
              >
                <span className="btn-icon">✕</span>
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};

export default FileUpload;