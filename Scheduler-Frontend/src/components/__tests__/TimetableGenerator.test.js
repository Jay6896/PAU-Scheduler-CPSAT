import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import TimetableGenerator from '../TimetableGenerator';
import * as api from '../../services/api';

// Mock the API module
jest.mock('../../services/api');

describe('TimetableGenerator', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders main components', () => {
    render(<TimetableGenerator />);
    
    expect(screen.getByText('Timetable Scheduler')).toBeInTheDocument();
    expect(screen.getByText('File Upload & Processing')).toBeInTheDocument();
    expect(screen.getByText('How to Use')).toBeInTheDocument();
  });

  test('shows instructions modal when button is clicked', () => {
    render(<TimetableGenerator />);
    
    const instructionsBtn = screen.getByText('How to Use');
    fireEvent.click(instructionsBtn);
    
    expect(screen.getByText(/How to use the Timetable Scheduler/i)).toBeInTheDocument();
    expect(screen.getByText('Download Template File')).toBeInTheDocument();
    expect(screen.getByText('Required Excel Sheets')).toBeInTheDocument();
  });

  test('closes instructions modal when close button is clicked', () => {
    render(<TimetableGenerator />);
    
    // Open modal
    const instructionsBtn = screen.getByText('How to Use');
    fireEvent.click(instructionsBtn);
    
    // Close modal
    const closeBtn = screen.getByLabelText('Close modal');
    fireEvent.click(closeBtn);
    
    expect(screen.queryByText(/How to use the Timetable Scheduler/i)).not.toBeInTheDocument();
  });

  test('handles file selection', () => {
    render(<TimetableGenerator />);
    
    const fileInput = screen.getByLabelText('Browse...');
    const file = new File(['test content'], 'test.xlsx', { 
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
    });
    
    fireEvent.change(fileInput, { target: { files: [file] } });
    
    expect(screen.getByDisplayValue('test.xlsx')).toBeInTheDocument();
    const selectedInfo = screen.getByText((_, el) => el?.classList?.contains('selected-file'));
    expect(selectedInfo).toHaveTextContent(/File loaded:/i);
    expect(selectedInfo).toHaveTextContent(/test\.xlsx/i);
    expect(screen.getByText('Generate Timetable')).toBeInTheDocument();
  });

  test('handles file reset', () => {
    render(<TimetableGenerator />);
    
    // Select a file
    const fileInput = screen.getByLabelText('Browse...');
    const file = new File(['test content'], 'test.xlsx', { 
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
    });
    
    fireEvent.change(fileInput, { target: { files: [file] } });
    
    // Reset
    const cancelBtn = screen.getByText('Cancel');
    fireEvent.click(cancelBtn);
    
    expect(screen.getByPlaceholderText('No file selected...')).toHaveValue('');
    expect(screen.queryByText(/File loaded/)).not.toBeInTheDocument();
  });

  test('handles successful timetable generation', async () => {
    // Mock API responses
    api.uploadFile.mockResolvedValue({ uploadId: 'test-file-id' });
    api.generateTimetable.mockResolvedValue({
      timetables_raw: [
        {
          student_group: 'Year 1 Computer Science',
          rows: []
        }
      ]
    });

    render(<TimetableGenerator />);
    
    // Select a file
    const fileInput = screen.getByLabelText('Browse...');
    const file = new File(['test content'], 'test.xlsx', { 
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
    });
    
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Generate timetable
    const generateBtn = screen.getByText('Generate Timetable');
    fireEvent.click(generateBtn);
    
    // Wait for results
    await waitFor(() => {
      expect(screen.getByText(/Timetable for Year 1 Computer Science/i)).toBeInTheDocument();
      expect(screen.getByText('Download Timetables')).toBeInTheDocument();
    }, { timeout: 4000 });
  });

  test('handles API errors during generation', async () => {
    // Mock API error
    api.uploadFile.mockRejectedValue(new Error('Upload failed'));

    render(<TimetableGenerator />);
    
    // Select a file
    const fileInput = screen.getByLabelText('Browse...');
    const file = new File(['test content'], 'test.xlsx', { 
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
    });
    
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Generate timetable
    const generateBtn = screen.getByText('Generate Timetable');
    fireEvent.click(generateBtn);
    
    // Wait for error
    await waitFor(() => {
      const errs = screen.getAllByText((_, el) => el?.classList?.contains('error-message'));
      expect(errs.some((el) => /upload failed/i.test(el.textContent || ''))).toBe(true);
    });
  });

  test('no download button before generation', () => {
    render(<TimetableGenerator />);

    expect(screen.queryByText('Download Timetables')).not.toBeInTheDocument();
  });
});