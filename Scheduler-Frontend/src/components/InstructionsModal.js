import React, { useEffect, useRef, useState } from 'react';
import './InstructionsModal.css';

const InstructionsModal = ({ isOpen, onClose }) => {
  const templateUrl = `/Timetable_Input_Template.xlsx?v=${encodeURIComponent(
    process.env.REACT_APP_TEMPLATE_VERSION || 'latest'
  )}`;

  const modalRef = useRef(null);
  const closeButtonRef = useRef(null);
  const [activeTab, setActiveTab] = useState('requirements');
  const [expandedImage, setExpandedImage] = useState(null);

  useEffect(() => {
    if (isOpen) {
      // Focus the close button when modal opens
      if (closeButtonRef.current) {
        closeButtonRef.current.focus();
      }
      // Ensure default tab each time modal opens
      setActiveTab('requirements');
      
      // Add body class to prevent scrolling
      document.body.classList.add('modal-open');
      
      // Handle escape key
      const handleEscape = (e) => {
        if (e.key === 'Escape') {
          if (expandedImage) {
            setExpandedImage(null);
          } else {
            onClose();
          }
        }
      };
      
      document.addEventListener('keydown', handleEscape);
      
      return () => {
        document.removeEventListener('keydown', handleEscape);
        document.body.classList.remove('modal-open');
      };
    }
  }, [isOpen, onClose, expandedImage]);

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      if (expandedImage) {
        setExpandedImage(null);
      } else {
        onClose();
      }
    }
  };

  // const handleDownloadTemplate = () => {
  //   // Create a link to download the template file
  //   const link = document.createElement('a');
  //   link.href = '/Timetable_Input_Template.xlsx';
  //   link.download = 'Timetable_Input_Template.xlsx';
  //   document.body.appendChild(link);
  //   link.click();
  //   document.body.removeChild(link);
  // };

  //Changes made
  const handleImageClick = (imageName) => {
    setExpandedImage(imageName);
  };

  if (!isOpen) return null;

  return (
    <div className="modal" onClick={handleOverlayClick}>
      <div className="modal-content" ref={modalRef} tabIndex="-1">
        <div className="modal-header">
          <h2 className="modal-title">How to use the Timetable Scheduler</h2>
          <button 
            className="close-btn" 
            onClick={onClose}
            ref={closeButtonRef}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        
        <div className="modal-body">
          <div className="tab-navigation">
            {/* Requirements first */}
            <button 
              className={`tab-button ${activeTab === 'requirements' ? 'active' : ''}`}
              onClick={() => setActiveTab('requirements')}
            >
              Input File Requirements
            </button>
            <button 
              className={`tab-button ${activeTab === 'uploading' ? 'active' : ''}`}
              onClick={() => setActiveTab('uploading')}
            >
              Uploading Files
            </button>
          </div>

          <div className="tab-content">
            {activeTab === 'uploading' && (
              <div className="uploading-tab">
                <div className="instruction-step">
                  <h4>1. Prepare Your Excel File</h4>
                  <p>Download our template file or ensure your Excel file follows the required format with the exact sheet names and column headers.</p>
                </div>
                
                <div className="instruction-step">
                  <h4>2. Upload Your File</h4>
                  <p>Click the "Choose File" button in the File Upload section and select your Excel file (.xlsx format only).</p>
                </div>
                
                <div className="instruction-step">
                  <h4>3. Wait for Processing</h4>
                  <p>The system will validate and parse your Excel file. Watch the progress bar for upload status.</p>
                </div>
                
                <div className="instruction-step">
                  <h4>4. Generate Timetable</h4>
                  <p>Once uploaded successfully, click "Generate Timetable" to create an optimized schedule using our genetic algorithm.</p>
                </div>
                
                <div className="instruction-step">
                  <h4>5. View Your Timetable</h4>
                  <p>Choose how to view your generated timetable:</p>
                  <ul>
                    <li><strong>View in iframe:</strong> See the timetable embedded in this page</li>
                    <li><strong>Open in new tab:</strong> Open the interactive timetable in a separate browser tab for full-screen viewing</li>
                  </ul>
                </div>
                
                <div className="instruction-step">
                  <h4>6. Interact with Your Timetable</h4>
                  <p>In the interactive view, you can:</p>
                  <ul>
                    <li>Drag and drop classes to different time slots</li>
                    <li>View constraint conflicts highlighted in red</li>
                    <li>Switch between different generated solutions</li>
                    <li>Export your final timetable</li>
                  </ul>
                </div>
              </div>
            )}

            {activeTab === 'requirements' && (
              <div className="requirements-tab">
                <div className="template-download">
                  <h4>Download Template File</h4>
                  <p>Use our pre-formatted template to ensure compatibility:</p>
                  <a
                  href={templateUrl}
                  download="Timetable_Input_Template.xlsx" // The 'download' attribute is key
                  className="download-template-btn"
                >
                  Download Timetable_Input_Template.xlsx
                </a>
                </div>

                <div className="sheet-requirements">
                  <h4>Required Excel Sheets</h4>
                  <p>Your Excel file must contain exactly these 4 sheets with these exact names:</p>
                  
                  <div className="sheet-list">
                    <div className="sheet-item">
                      <h5>1. Courses</h5>
                      <p>Contains course information with columns: Course Code, Course Name, Credits, Duration, Assigned Lecturer Emails</p>
                      <div className="format-details">
                        <strong>⚠️ Important:</strong> For multiple lecturers, separate emails with "/" or "," (e.g., "prof1@pau.edu.ng/prof2@pau.edu.ng")
                      </div>
                    </div>
                    
                    <div className="sheet-item">
                      <h5>2. Lecturers</h5>
                      <p>Contains lecturer information with columns: Lecturer Email, Lecturer Name, Department, Status, Available Days, Available Times</p>
                      <div className="format-details">
                        <strong>⚠️ Important:</strong>
                        <ul>
                          <li><strong>Status:</strong> Must be exactly "Full-Time" or "Adjunct"</li>
                          <li><strong>Available Days:</strong> Use format "Mon,Tue,Wed,Thu,Fri" (comma-separated, no spaces)</li>
                          <li><strong>Available Times:</strong> Use exact time format as shown in image example</li>
                        </ul>
                      </div>
                    </div>
                    
                    <div className="sheet-item">
                      <h5>3. Student Groups</h5>
                      <p>Contains student group information with columns: Group ID, Group Name, Level, Department, Size, Building</p>
                    </div>
                    
                    <div className="sheet-item">
                      <h5>4. Classrooms</h5>
                      <p>Contains room information with columns: Room ID, Room Name, Capacity, Type, Equipment</p>
                    </div>
                  </div>
                </div>

                <div className="format-examples">
                  <h4>Format Examples</h4>
                  <p>Required column structure for each sheet. Click "View Image Example" to see the exact Excel format:</p>
                  
                  <div className="format-tables">
                    <div className="format-table">
                      <div className="table-header">
                        <h5>Courses Sheet</h5>
                        <button 
                          className="view-image-btn"
                          onClick={() => handleImageClick('Columns For Courses Sheet.png')}
                        >
                          View Image Example
                        </button>
                      </div>
                      <div className="table-wrapper">
                        <table className="example-table">
                          <thead>
                            <tr>
                              <th>Course Code</th>
                              <th>Course Name</th>
                              <th>Course Type</th>
                              <th>Credit Units</th>
                              <th>Classroom Type</th>
                              <th>Assigned Lecturer Emails</th>
                              <th>Student Group 1</th>
                              <th>Student Group 2</th>
                              <th>Student Group 3</th>
                              <th>Student Group 4</th>
                              <th>Department</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>CSC101</td>
                              <td>Introduction to Programming</td>
                              <td>Lecture</td>
                              <td>3</td>
                              <td>Computer Lab</td>
                              <td>prof.smith@pau.edu.ng</td>
                              <td>CSC 100</td>
                              <td>SEN 100</td>
                              <td></td>
                              <td></td>
                              <td>Computer Science</td>
                            </tr>
                            <tr>
                              <td>MTH201</td>
                              <td>Calculus II</td>
                              <td>Lecture</td>
                              <td>4</td>
                              <td>Lecture Hall</td>
                              <td>dr.johnson@pau.edu.ng/prof.adams@pau.edu.ng</td>
                              <td>CSC 200 - 1</td>
                              <td>CSC 200 - 2</td>
                              <td>SEN 200</td>
                              <td></td>
                              <td>Mathematics</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                    
                    <div className="format-table">
                      <div className="table-header">
                        <h5>Lecturers Sheet</h5>
                        <button 
                          className="view-image-btn"
                          onClick={() => handleImageClick('Columns For Lecturer Sheet.png')}
                        >
                          View Image Example
                        </button>
                      </div>
                      <div className="table-wrapper">
                        <table className="example-table">
                          <thead>
                            <tr>
                              <th>Lecturer Email</th>
                              <th>Lecturer Name</th>
                              <th>Department</th>
                              <th>Status</th>
                              <th>Available Days</th>
                              <th>Available Times</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>F001</td>
                              <td>Dr. Smith</td>
                              <td>Computer Science</td>
                              <td>Full-Time</td>
                              <td>Mon,Tue,Wed,Thu,Fri</td>
                              <td>08:30-18:30</td>
                            </tr>
                            <tr>
                              <td>F002</td>
                              <td>Prof. Johnson</td>
                              <td>Mathematics</td>
                              <td>Adjunct</td>
                              <td>Mon,Wed,Fri</td>
                              <td>10:30-15:30</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                    
                    <div className="format-table">
                      <div className="table-header">
                        <h5>Student Groups Sheet</h5>
                        <button 
                          className="view-image-btn"
                          onClick={() => handleImageClick('Columns For Student Groups Sheet.png')}
                        >
                          View Image Example
                        </button>
                      </div>
                      <div className="table-wrapper">
                        <table className="example-table">
                          <thead>
                            <tr>
                              <th>Group ID</th>
                              <th>Group Name</th>
                              <th>Level</th>
                              <th>Department</th>
                              <th>Size</th>
                              <th>Building</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>G001</td>
                              <td>CS Year 1 Group A</td>
                              <td>100</td>
                              <td>Computer Science</td>
                              <td>30</td>
                              <td>SST</td>
                            </tr>
                            <tr>
                              <td>G002</td>
                              <td>Math Year 2 Group B</td>
                              <td>200</td>
                              <td>Mathematics</td>
                              <td>25</td>
                              <td>TYD</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                    
                    <div className="format-table">
                      <div className="table-header">
                        <h5>Classrooms Sheet</h5>
                        <button 
                          className="view-image-btn"
                          onClick={() => handleImageClick('Columns For Classroom Sheet.png')}
                        >
                          View Image Example
                        </button>
                      </div>
                      <div className="table-wrapper">
                        <table className="example-table">
                          <thead>
                            <tr>
                              <th>Room ID</th>
                              <th>Room Name</th>
                              <th>Capacity</th>
                              <th>Type</th>
                              <th>Equipment</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>R001</td>
                              <td>Lecture Hall A</td>
                              <td>50</td>
                              <td>Lecture</td>
                              <td>Projector,Audio</td>
                            </tr>
                            <tr>
                              <td>R002</td>
                              <td>Computer Lab 1</td>
                              <td>30</td>
                              <td>Lab</td>
                              <td>Computers,Projector</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                  
                  <div className="sheets-overview">
                    <div className="sheets-overview-header">
                      <h5>Required Sheets Overview</h5>
                      <button 
                        className="view-image-btn"
                        onClick={() => handleImageClick('Sheets Required.png')}
                      >
                        View Sheets Overview
                      </button>
                    </div>
                    <p>Click the button above to see how all four required sheets should appear in your Excel workbook.</p>
                  </div>
                </div>

                <div className="important-notes">
                  <h4>⚠️ Important Notes</h4>
                  <ul>
                    <li><strong>Column names must match exactly</strong> - case sensitive</li>
                    <li><strong>Sheet names must be exactly:</strong> "Courses", "Lecturers", "Student Groups", "Classrooms"</li>
                    <li><strong>File format:</strong> .xlsx only (not .xls or .csv)</li>
                    <li><strong>No empty rows</strong> between headers and data</li>
                    <li><strong>UTF-8 encoding</strong> recommended for special characters</li>
                  </ul>
                  
                  <div className="format-specifics">
                    <h5>Format-Specific Requirements</h5>
                    
                    <div className="format-requirement">
                      <h6>Courses Sheet:</h6>
                      <ul>
                        <li><strong>Assigned Lecturer Emails:</strong> For multiple lecturers, use "/" or "," to separate emails</li>
                        <li>Example: "prof1@pau.edu.ng/prof2@pau.edu.ng" or "prof1@pau.edu.ng,prof2@pau.edu.ng"</li>
                      </ul>
                    </div>
                    
                    <div className="format-requirement">
                      <h6>Lecturers Sheet:</h6>
                      <ul>
                        <li><strong>Employment Type:</strong> Must be exactly "Full-Time" or "Adjunct" (case-sensitive)</li>
                        <li><strong>Available Days:</strong> Use format "Mon,Tue,Wed,Thu,Fri" (comma-separated, no spaces)</li>
                        <li><strong>Available Times:</strong> Follow exact time format as shown in image (e.g., "8:00 AM - 5:00 PM")</li>
                      </ul>
                    </div>
                    
                    <div className="format-requirement">
                      <h6>General:</h6>
                      <ul>
                        <li><strong>All text values</strong> must match the exact format and case shown in examples</li>
                        <li><strong>Time formats</strong> must follow the convention shown in the image examples</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Image Expansion Modal */}
      {expandedImage && (
        <div className="image-modal" onClick={() => setExpandedImage(null)}>
          <div className="image-modal-content">
            <button 
              className="image-close-btn" 
              onClick={() => setExpandedImage(null)}
              aria-label="Close image"
            >
              ×
            </button>
            <img 
              src={`/images/${expandedImage}`} 
              alt={`Excel format example: ${expandedImage}`}
              className="expanded-image"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default InstructionsModal;