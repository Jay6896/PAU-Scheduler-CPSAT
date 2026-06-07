import React, { useState, useEffect, useCallback } from 'react';
import './RoomModal.css';
import LecturerModal from './LecturerModal';

const RoomModal = ({
  isOpen,
  onClose,
  onConfirm,
  currentRoom,
  roomsData,
  timetables,
  currentRow,
  currentCol,
  isManual,
  isMultiLecturer,
  courseName,
  currentLecturer,
  lecturerOptions,
  mode,
  autoOpenLecturerModal,
  autoApplyLecturerChange,
}) => {
  const [selectedRoom, setSelectedRoom] = useState(currentRoom);
  const [searchTerm, setSearchTerm] = useState('');
  const [buildingFilter, setBuildingFilter] = useState('ALL');
  const [showAvailableOnly, setShowAvailableOnly] = useState(true);
  const [roomUsage, setRoomUsage] = useState({});

  const [lecturerModalOpen, setLecturerModalOpen] = useState(false);
  const [selectedLecturer, setSelectedLecturer] = useState(null);

  const computeRoomUsage = useCallback(() => {
    const usage = {};
    
    if (!timetables || currentRow === undefined || currentCol === undefined) return;

    timetables.forEach((timetableData) => {
      const timetable = timetableData.timetable || [];
      if (currentRow < timetable.length && currentCol < timetable[currentRow].length) {
        const cell = timetable[currentRow][currentCol];
        const roomMatch = cell?.match(/Room:\s*([^\n,]+)/);
        if (roomMatch && roomMatch[1]) {
          const room = roomMatch[1].trim();
          if (room && room !== 'Unknown') {
            usage[room] = timetableData.student_group?.name || timetableData.student_group || 'Unknown Group';
          }
        }
      }
    });

    setRoomUsage(usage);
  }, [timetables, currentRow, currentCol]);

  useEffect(() => {
    if (isOpen) {
      setSelectedRoom(currentRoom);
      computeRoomUsage();

      // Reset transient state per-open
      setSearchTerm('');
      setBuildingFilter('ALL');
      setShowAvailableOnly(true);

      const current = String(currentLecturer || '').trim();
      if (current && !current.includes(',')) {
        setSelectedLecturer(current);
      } else if (Array.isArray(lecturerOptions) && lecturerOptions.length === 1) {
        setSelectedLecturer(String(lecturerOptions[0]).trim());
      } else {
        setSelectedLecturer(null);
      }

      if (autoOpenLecturerModal && isMultiLecturer) {
        // Defer slightly so RoomModal renders before opening nested modal.
        setTimeout(() => setLecturerModalOpen(true), 0);
      }
    }
  }, [isOpen, currentRoom, computeRoomUsage, currentLecturer, lecturerOptions, autoOpenLecturerModal, isMultiLecturer]);

  if (!isOpen) return null;

  const filteredRooms = (roomsData || []).filter(room => {
    const matchesSearch = room.name?.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesBuilding = buildingFilter === 'ALL' || room.building === buildingFilter;
    const isAvailable = !roomUsage[room.name];
    const matchesAvailability = !showAvailableOnly || isAvailable;

    return matchesSearch && matchesBuilding && matchesAvailability;
  });

  const requiresLecturerSelection = Array.isArray(lecturerOptions) && lecturerOptions.length > 1;

  const handleConfirm = () => {
    if (!selectedRoom) return;
    if (requiresLecturerSelection && !selectedLecturer) return;
    onConfirm({ room: selectedRoom, lecturer: selectedLecturer });
  };

  const handleDelete = () => {
    onConfirm({ room: 'FREE', lecturer: null });
  };

  // Determine if this is a manual/missing class (Step 5)
  // We can infer it if the student group logic relies on the manual_cells prop
  // But passed props don't include it. We can treat any modification here as "Manual" action.
  // The user requirement says: "DELETE SCHEDULE button which should only be available to manually scheduled classes."
  // And "manual_modal" vs "regular".
  // Since we don't have the explicit manual flag here, we can pass it or infer it.
  // However, usually "Delete Schedule" implies freeing up a slot. 
  // If the prompt implies that purely algorithmic slots shouldn't be deleted, we need that flag.
  // For now, I will assume all slots can be cleared (as standard Dash behavior allowed it),
  // but if strictly only manual, we might need to check if it was manually placed.
  // Given I can't easily change the prop signature across all files without more context, 
  // I will style it distinctively.
  
  return (
    <>
      <div className="modal-overlay" onClick={onClose}></div>
      <div className="room-selection-modal">
        <div className="modal-header">
          <h3 className="modal-title">
            {mode === 'schedule' ? 'Select Classroom (Manual Schedule)' : 'Select Classroom'}
            {courseName ? ` - ${courseName}` : ''}
            {selectedRoom ? ` - ${selectedRoom}` : ''}
          </h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <input
          type="text"
          className="room-search"
          placeholder="Search classrooms..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '15px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <label style={{ display: 'flex', alignItems: 'center', fontSize: '13px', color: '#11214D', fontWeight: '500' }}>
              <input
                type="checkbox"
                checked={showAvailableOnly}
                onChange={(e) => setShowAvailableOnly(e.target.checked)}
                style={{ marginRight: '6px' }}
              />
              Available only
            </label>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {isMultiLecturer && (
              <button
                onClick={() => setLecturerModalOpen(true)}
                type="button"
                style={{ backgroundColor: '#11214D', color: 'white', padding: '6px 12px', border: 'none', borderRadius: '3px', cursor: 'pointer', fontWeight: '600', fontSize: '12px', fontFamily: 'Poppins, sans-serif', boxShadow: '0 1px 3px rgba(0,0,0,0.12)' }}
                title="Change the primary lecturer for this cell"
              >
                Change Primary Lecturer
              </button>
            )}

            <select
              value={buildingFilter}
              onChange={(e) => setBuildingFilter(e.target.value)}
              style={{ width: '180px', fontSize: '13px', padding: '6px 12px', borderRadius: '6px', border: '2px solid #e0e0e0' }}
            >
              <option value="ALL">All buildings</option>
              <option value="TYD">TYD</option>
              <option value="SST">SST</option>
            </select>
          </div>
        </div>

        <div className="room-options">
          {filteredRooms.length === 0 ? (
            <div style={{ padding: '20px', textAlign: 'center', color: '#666' }}>
              No rooms found matching your criteria
            </div>
          ) : (
            filteredRooms.map((room, idx) => {
              const isOccupied = roomUsage[room.name];
              const isSelected = selectedRoom === room.name;

              return (
                <button
                  key={idx}
                  className={`room-option ${isSelected ? 'selected' : ''} ${isOccupied ? 'occupied' : 'available'}`}
                  onClick={() => setSelectedRoom(room.name)}
                >
                  <span>{room.name}</span>
                  <span className="room-info">
                    {isOccupied ? `Occupied by ${isOccupied}` : 'Available'} | {room.building} | Capacity: {room.capacity}
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
          >
            Cancel
          </button>
          
          {isManual && (
            <button
              onClick={handleDelete}
              style={{ backgroundColor: '#dc3545', color: 'white', padding: '8px 16px', border: 'none', borderRadius: '5px', cursor: 'pointer', fontWeight: '600' }}
            >
              Delete Schedule
            </button>
          )}
          
          <button
            onClick={handleConfirm}
            style={{ backgroundColor: '#11214D', color: 'white', padding: '8px 16px', border: 'none', borderRadius: '5px', cursor: 'pointer' }}
            disabled={!selectedRoom || (requiresLecturerSelection && !selectedLecturer)}
          >
            Confirm
          </button>
        </div>
      </div>

      {lecturerModalOpen && (
        <LecturerModal
          isOpen={lecturerModalOpen}
          onClose={() => setLecturerModalOpen(false)}
          onConfirm={(lect) => {
            const next = String(lect || '').trim();
            if (!next) return;

            setSelectedLecturer(next);

            if (autoApplyLecturerChange) {
              // Apply immediately (user expectation: click lecturer name -> cell updates)
              if (selectedRoom) {
                onConfirm({ room: selectedRoom, lecturer: next });
              }
              setLecturerModalOpen(false);
              onClose();
              return;
            }

            setLecturerModalOpen(false);
          }}
          title={courseName ? `Select Lecturer - ${courseName}` : 'Select Lecturer'}
          lecturerOptions={lecturerOptions}
          currentLecturer={selectedLecturer || currentLecturer}
        />
      )}
    </>
  );
};

export default RoomModal;
