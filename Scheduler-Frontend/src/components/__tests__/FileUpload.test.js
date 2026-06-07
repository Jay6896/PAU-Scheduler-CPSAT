import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import FileUpload from '../FileUpload';

// Mock environment variables
const originalEnv = process.env;

beforeEach(() => {
  jest.resetModules();
  process.env = {
    ...originalEnv,
    REACT_APP_ALLOWED_FILE_TYPES: '.xlsx,.xls',
    REACT_APP_MAX_FILE_SIZE: '10485760'
  };
});

afterEach(() => {
  process.env = originalEnv;
});

describe('FileUpload', () => {
  const mockProps = {
    selectedFile: null,
    onFileSelect: jest.fn(),
    onFileReset: jest.fn(),
    onGenerate: jest.fn(),
    isProcessing: false,
    progress: 0,
    progressText: '',
    error: ''
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders file upload interface', () => {
    render(<FileUpload {...mockProps} />);
    
    expect(screen.getByText('File Upload & Processing')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('No file selected...')).toBeInTheDocument();
    expect(screen.getByText('Browse...')).toBeInTheDocument();
  });

  test('shows action buttons when file is selected', () => {
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    render(<FileUpload {...mockProps} selectedFile={file} />);
    
    expect(screen.getByText('Generate Timetable')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  test('displays selected file information', () => {
    const file = new File(['test content'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    render(<FileUpload {...mockProps} selectedFile={file} />);
    
    expect(screen.getByDisplayValue('test.xlsx')).toBeInTheDocument();
    const selectedInfo = screen.getByText((_, el) => el?.classList?.contains('selected-file'));
    expect(selectedInfo).toHaveTextContent(/File loaded:/i);
    expect(selectedInfo).toHaveTextContent(/test\.xlsx/i);
  });

  test('handles file selection', () => {
    render(<FileUpload {...mockProps} />);
    
    const fileInput = screen.getByLabelText('Browse...');
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    // Mock file validation
    Object.defineProperty(file, 'size', { value: 1024 });
    
    fireEvent.change(fileInput, { target: { files: [file] } });
    
    expect(mockProps.onFileSelect).toHaveBeenCalledWith(file);
  });

  test('validates file type', () => {
    // Mock alert
    global.alert = jest.fn();
    
    render(<FileUpload {...mockProps} />);
    
    const fileInput = screen.getByLabelText('Browse...');
    const invalidFile = new File(['test'], 'test.pdf', { type: 'application/pdf' });
    
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });
    
    expect(global.alert).toHaveBeenCalledWith('Please select a valid Excel file (.xlsx or .xls)');
    expect(mockProps.onFileSelect).not.toHaveBeenCalled();
  });

  test('validates file size', () => {
    // Mock alert
    global.alert = jest.fn();
    
    render(<FileUpload {...mockProps} />);
    
    const fileInput = screen.getByLabelText('Browse...');
    const largeFile = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    // Mock large file size
    Object.defineProperty(largeFile, 'size', { value: 20 * 1024 * 1024 }); // 20MB
    
    fireEvent.change(fileInput, { target: { files: [largeFile] } });
    
    expect(global.alert).toHaveBeenCalledWith('File size must be less than 10MB');
    expect(mockProps.onFileSelect).not.toHaveBeenCalled();
  });

  test('shows progress bar when processing', () => {
    render(<FileUpload {...mockProps} isProcessing={true} progress={50} progressText="Processing..." />);
    
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText('Processing...')).toBeInTheDocument();
  });

  test('shows error message when provided', () => {
    render(<FileUpload {...mockProps} error="Test error message" />);

    const err = screen.getByText((_, el) => el?.classList?.contains('error-message'));
    expect(err).toHaveTextContent(/Error:/i);
    expect(err).toHaveTextContent(/Test error message/i);
  });

  test('handles generate button click', () => {
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    render(<FileUpload {...mockProps} selectedFile={file} />);
    
    const generateBtn = screen.getByText('Generate Timetable');
    fireEvent.click(generateBtn);
    
    expect(mockProps.onGenerate).toHaveBeenCalled();
  });

  test('handles cancel button click', () => {
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    render(<FileUpload {...mockProps} selectedFile={file} />);
    
    const cancelBtn = screen.getByText('Cancel');
    fireEvent.click(cancelBtn);
    
    expect(mockProps.onFileReset).toHaveBeenCalled();
  });

  test('disables buttons when processing', () => {
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    render(<FileUpload {...mockProps} selectedFile={file} isProcessing={true} />);
    
    expect(screen.getByText('Processing...')).toBeDisabled();
    expect(screen.getByText('Cancel')).toBeDisabled();
  });

  test('handles drag and drop', () => {
    render(<FileUpload {...mockProps} />);
    
    const uploadSection = screen.getByText('File Upload & Processing').closest('.upload-section');
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    // Mock file validation for drag and drop
    Object.defineProperty(file, 'size', { value: 1024 });
    
    fireEvent.dragOver(uploadSection);
    expect(uploadSection).toHaveClass('dragover');
    
    fireEvent.drop(uploadSection, {
      dataTransfer: {
        files: [file]
      }
    });
    
    expect(mockProps.onFileSelect).toHaveBeenCalledWith(file);
    expect(uploadSection).not.toHaveClass('dragover');
  });
});