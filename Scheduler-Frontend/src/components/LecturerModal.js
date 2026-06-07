import React, { useEffect, useMemo, useState } from 'react';
import './RoomModal.css';

const LecturerModal = ({ isOpen, onClose, onConfirm, title, lecturerOptions, currentLecturer }) => {
  const options = useMemo(() => {
    const arr = Array.isArray(lecturerOptions) ? lecturerOptions : [];
    return arr.map((l) => String(l).trim()).filter(Boolean);
  }, [lecturerOptions]);

  const [selectedLecturer, setSelectedLecturer] = useState(currentLecturer || null);

  useEffect(() => {
    if (!isOpen) return;

    const current = String(currentLecturer || '').trim();
    if (current && !current.includes(',')) {
      setSelectedLecturer(current);
      return;
    }

    if (options.length === 1) {
      setSelectedLecturer(options[0]);
      return;
    }

    setSelectedLecturer(null);
  }, [isOpen, currentLecturer, options]);

  if (!isOpen) return null;

  return (
    <>
      <div className="modal-overlay" onClick={onClose}></div>
      <div className="room-selection-modal">
        <div className="modal-header">
          <h3 className="modal-title">{title || 'Select Lecturer'}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="room-options">
          {options.length === 0 ? (
            <div style={{ padding: '20px', textAlign: 'center', color: '#666' }}>
              No lecturer options available.
            </div>
          ) : (
            options.map((lect, idx) => {
              const isSelected = selectedLecturer === lect;
              return (
                <button
                  key={`${lect}-${idx}`}
                  className={`room-option ${isSelected ? 'selected' : ''} available`}
                  onClick={() => setSelectedLecturer(lect)}
                  type="button"
                >
                  <span>{lect}</span>
                  <span className="room-info">Available</span>
                </button>
              );
            })
          )}
        </div>

        <div style={{ textAlign: 'right', marginTop: '20px', paddingTop: '15px', borderTop: '1px solid #f0f0f0', display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{ backgroundColor: '#f5f5f5', color: '#666', padding: '8px 16px', border: '1px solid #ddd', borderRadius: '5px', cursor: 'pointer' }}
            type="button"
          >
            Cancel
          </button>

          <button
            onClick={() => {
              if (!selectedLecturer) return;
              onConfirm(selectedLecturer);
            }}
            style={{ backgroundColor: '#11214D', color: 'white', padding: '8px 16px', border: 'none', borderRadius: '5px', cursor: 'pointer', fontWeight: '600' }}
            disabled={!selectedLecturer}
            type="button"
          >
            Confirm
          </button>
        </div>
      </div>
    </>
  );
};

export default LecturerModal;
