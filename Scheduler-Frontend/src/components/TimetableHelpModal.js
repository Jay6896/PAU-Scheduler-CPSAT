import React, { useEffect, useRef } from 'react';
import './TimetableHelpModal.css';

const TimetableHelpModal = ({ isOpen, onClose }) => {
  const modalRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <>
      <div
        className="modal-overlay"
        id="help-modal-overlay"
        onClick={onClose}
        role="presentation"
      />
      <div className="help-modal" id="help-modal" ref={modalRef} role="dialog" aria-modal="true">
        <div className="modal-header">
          <h3
            className="modal-title"
            style={{ color: '#11214D', fontWeight: '600', marginBottom: '0', fontSize: '20px' }}
          >
            Timetable Help Guide
          </h3>
          <button className="modal-close" id="help-modal-close-btn" onClick={onClose} type="button" aria-label="Close">
            ×
          </button>
        </div>

        <div>
          <div className="help-note">
            <strong>NOTE: </strong>
            Ensure all Lecturer names, emails and other details are inputted correctly to prevent errors
          </div>

          <div className="help-section">
            <h4 style={{ color: '#11214D', fontWeight: '600', marginBottom: '10px', fontSize: '16px' }}>
              How to Use the Timetable:
            </h4>
            <p>• Click and drag any class cell to swap it with another cell</p>
            <p>• Double-click any cell to view and change the classroom for that class</p>
            <p>
              • Cells with asterisks (*) mean the course has multiple lecturers. Double click to set the lecturer lecturing
              for that student group
            </p>
            <p>• Use the navigation arrows (‹ ›) to switch between different student groups</p>
            <p>• Click 'View Errors' to see constraint violations and conflicts</p>
            <p>• Click on any error in the 'View Errors' list to jump to the relevant student group timetable</p>
          </div>

          <div className="help-section">
            <h4 style={{ color: '#11214D', fontWeight: '600', marginBottom: '10px', fontSize: '16px' }}>
              Cell Color Meanings:
            </h4>
            <div className="color-legend">
              <div className="color-item">
                <div className="color-box normal" />
                <span>Normal class - No conflicts</span>
              </div>
              <div className="color-item">
                <div className="color-box manual" />
                <span>Manually Scheduled - Class scheduled manually from the 'Missing Classes' list.</span>
              </div>
              <div className="color-item">
                <div className="color-box break" />
                <span>Break time - Classes cannot be scheduled</span>
              </div>
              <div className="color-item">
                <div className="color-box room-conflict" />
                <span>Room conflict - Same classroom used by multiple groups</span>
              </div>
              <div className="color-item">
                <div className="color-box lecturer-conflict" />
                <span>Lecturer conflict - Same lecturer teaching multiple groups</span>
              </div>
              <div className="color-item">
                <div className="color-box both-conflict" />
                <span>Multiple conflicts - Both room and lecturer issues</span>
              </div>
            </div>
          </div>
        </div>

        <div
          style={{
            textAlign: 'center',
            marginTop: '25px',
            paddingTop: '20px',
            borderTop: '2px solid #f0f0f0',
          }}
        >
          <button
            id="help-close-btn"
            onClick={onClose}
            type="button"
            style={{
              backgroundColor: '#11214D',
              color: 'white',
              padding: '10px 20px',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontFamily: 'Poppins, sans-serif',
              fontSize: '14px',
              fontWeight: '600',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </>
  );
};

export default TimetableHelpModal;
