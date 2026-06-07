import React, { useMemo, useState, useEffect } from 'react';
import './RoomModal.css';

const normalizeMissingItem = (item) => {
  if (!item) return null;

  if (typeof item === 'string') {
    const course = item.trim();
    if (!course) return null;
    return { course, lecturerOptions: [], lecturer: null, raw: item };
  }

  if (typeof item === 'object') {
    const course =
      item.course_name ||
      item.course ||
      item.courseCode ||
      item.code ||
      item.name ||
      item.title ||
      '';

    const courseTrimmed = String(course || '').trim();
    if (!courseTrimmed) return null;

    const lecturersRaw =
      item.lecturer_options ||
      item.lecturers ||
      item.lecturer ||
      item.instructors ||
      item.instructor ||
      null;

    let lecturerOptions = [];
    let lecturer = null;

    if (Array.isArray(lecturersRaw)) {
      lecturerOptions = lecturersRaw.map((l) => String(l).trim()).filter(Boolean);
    } else if (typeof lecturersRaw === 'string') {
      const parts = lecturersRaw.split(',').map((p) => p.trim()).filter(Boolean);
      if (parts.length > 1) lecturerOptions = parts;
      else lecturer = parts[0] || null;
    }

    return { course: courseTrimmed, lecturerOptions, lecturer, raw: item };
  }

  return null;
};

const getGroupName = (currentGroup) => {
  const g = currentGroup?.student_group;
  if (g && typeof g === 'object' && g.name) return g.name;
  if (typeof g === 'string') return g;
  if (currentGroup?.name) return currentGroup.name;
  return 'Unknown Group';
};

const extractMissingClasses = (constraintDetails, currentGroup) => {
  const groupName = getGroupName(currentGroup);

  const direct = currentGroup?.missing_classes || currentGroup?.missingClasses;
  if (Array.isArray(direct)) return direct;

  const cd = constraintDetails || {};

  const byGroup =
    cd.missing_classes ||
    cd.missingClasses ||
    cd.MissingClasses ||
    cd['Missing Classes'] ||
    cd['missing classes'];

  if (byGroup && typeof byGroup === 'object') {
    const exact = byGroup[groupName];
    if (Array.isArray(exact)) return exact;

    const lowerKey = Object.keys(byGroup).find((k) => String(k).toLowerCase() === String(groupName).toLowerCase());
    if (lowerKey && Array.isArray(byGroup[lowerKey])) return byGroup[lowerKey];
  }

  return [];
};

const MissingClassesModal = ({ isOpen, onClose, constraintDetails, currentGroup, onScheduleClass }) => {
  const [selectedIdx, setSelectedIdx] = useState(null);

  const groupName = useMemo(() => getGroupName(currentGroup), [currentGroup]);

  const normalizedItems = useMemo(() => {
    const raw = extractMissingClasses(constraintDetails, currentGroup);
    return (raw || []).map(normalizeMissingItem).filter(Boolean);
  }, [constraintDetails, currentGroup]);

  useEffect(() => {
    if (isOpen) {
      setSelectedIdx(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const selected = typeof selectedIdx === 'number' ? normalizedItems[selectedIdx] : null;

  return (
    <>
      <div className="modal-overlay" onClick={onClose}></div>
      <div className="room-selection-modal">
        <div className="modal-header">
          <h3 className="modal-title">Missing Classes - {groupName}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="room-options">
          {normalizedItems.length === 0 ? (
            <div style={{ padding: '20px', textAlign: 'center', color: '#666' }}>
              No missing classes found for this student group.
            </div>
          ) : (
            normalizedItems.map((item, idx) => {
              const isSelected = selectedIdx === idx;
              const hasMultiLecturer = Array.isArray(item.lecturerOptions) && item.lecturerOptions.length > 1;

              return (
                <button
                  key={`${item.course}-${idx}`}
                  className={`room-option ${isSelected ? 'selected' : ''} available`}
                  onClick={() => setSelectedIdx(idx)}
                  type="button"
                >
                  <span>{item.course}</span>
                  <span className="room-info">
                    {hasMultiLecturer ? 'Multiple lecturers (*)' : (item.lecturer ? `Lecturer: ${item.lecturer}` : 'Lecturer: Unknown')}
                  </span>
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
              if (!selected) return;
              onScheduleClass(selected);
            }}
            style={{ backgroundColor: '#11214D', color: 'white', padding: '8px 16px', border: 'none', borderRadius: '5px', cursor: 'pointer', fontWeight: '600' }}
            disabled={!selected}
            type="button"
          >
            Add to Slot
          </button>
        </div>
      </div>
    </>
  );
};

export default MissingClassesModal;
