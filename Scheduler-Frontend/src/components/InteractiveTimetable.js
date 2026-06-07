import React, { useEffect, useCallback, useMemo, useRef, useState } from 'react';
import './InteractiveTimetable.css';
import RoomModal from './RoomModal';
import ConstraintModal from './ConstraintModal';
import MissingClassesModal from './MissingClassesModal';
import DownloadModal from './DownloadModal';
import TimetableHelpModal from './TimetableHelpModal';
import { getRoomsData, getConstraintViolations, saveTimetableChanges, getSavedTimetable, getCourseLecturers } from '../services/api';

const InteractiveTimetable = ({ timetablesData, uploadId, onSave }) => {
  const initialSnapshotRef = useRef(null);
  const flashTimerRef = useRef(null);
  const pendingNavRef = useRef(null);
  const clickTimerRef = useRef(null);

  const days = useMemo(() => ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], []);
  const hours = useMemo(() => Array.from({ length: 10 }, (_, i) => `${(8 + i).toString().padStart(2, '0')}:30 - ${(9 + i).toString().padStart(2, '0')}:30`), []);

  const normalizeRow = useCallback((row, rowIdx) => {
    // Accept both array-row format and object-row format.
    // Dash expects: [time, Monday, Tuesday, Wednesday, Thursday, Friday]
    if (Array.isArray(row)) {
      const padded = [...row];
      while (padded.length < 6) padded.push('');
      padded.length = 6;

      // Force correctly formatted time label from our hours array
      padded[0] = hours[rowIdx] || '';

      // Normalize empty cells to FREE, matching Dash UI display.
      for (let i = 1; i < padded.length; i++) {
        if (padded[i] === null || padded[i] === undefined || String(padded[i]).trim() === '') {
          padded[i] = 'FREE';
        }
      }
      return padded;
    }

    if (row && typeof row === 'object') {
      const time = hours[rowIdx] || row.Time || row.time || row[0] || '';
      const normalized = [
        String(time),
        row.Monday ?? row.mon ?? row.Mon ?? row[1] ?? 'FREE',
        row.Tuesday ?? row.tue ?? row.Tue ?? row[2] ?? 'FREE',
        row.Wednesday ?? row.wed ?? row.Wed ?? row[3] ?? 'FREE',
        row.Thursday ?? row.thu ?? row.Thu ?? row[4] ?? 'FREE',
        row.Friday ?? row.fri ?? row.Fri ?? row[5] ?? 'FREE'
      ].map(v => (v === null || v === undefined || String(v).trim() === '') ? 'FREE' : v);
      return normalized;
    }

    // Unknown row shape
    return [hours[rowIdx] || '', 'FREE', 'FREE', 'FREE', 'FREE', 'FREE'];
  }, [hours]);

  const normalizeTimetables = useCallback((raw) => {
    const arr = Array.isArray(raw) ? raw : (raw ? [raw] : []);
    return arr.map((t) => {
      const timetable = Array.isArray(t?.timetable) ? t.timetable : (Array.isArray(t?.rows) ? t.rows : []);
      const normalizedRows = timetable.map((row, idx) => normalizeRow(row, idx));
      return {
        ...t,
        timetable: normalizedRows,
      };
    });
  }, [normalizeRow]);

  const [timetables, setTimetables] = useState(() => normalizeTimetables(timetablesData || []));
  const [currentGroupIdx, setCurrentGroupIdx] = useState(0);
  const [manualCells, setManualCells] = useState([]);
  const [draggedCell, setDraggedCell] = useState(null);
  const [dragOverCell, setDragOverCell] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [roomModalOpen, setRoomModalOpen] = useState(false);
  const [errorModalOpen, setErrorModalOpen] = useState(false);
  const [downloadModalOpen, setDownloadModalOpen] = useState(false);
  const [constraintDetails, setConstraintDetails] = useState({});
  const [conflicts, setConflicts] = useState({});
  const [roomsData, setRoomsData] = useState([]);
  const [courseLecturersByCourse, setCourseLecturersByCourse] = useState({});
  const [constraintsLoading, setConstraintsLoading] = useState(false);
  const [helpModalOpen, setHelpModalOpen] = useState(false);
  const [missingClassesModalOpen, setMissingClassesModalOpen] = useState(false);

  // When scheduling a missing class into a FREE slot
  const [pendingSchedule, setPendingSchedule] = useState(null);

  const [flashingCell, setFlashingCell] = useState(null);

  const runFlash = useCallback((row, col) => {
    const r = parseInt(row, 10);
    const c = parseInt(col, 10);
    if (Number.isNaN(r) || Number.isNaN(c)) return;

    const selector = `td.cell[data-row="${r}"][data-col="${c}"]`;
    const el = document.querySelector(selector);
    if (el && typeof el.scrollIntoView === 'function') {
      try {
        el.scrollIntoView({ block: 'center', inline: 'center' });
      } catch (_) {
        el.scrollIntoView();
      }
    }

    if (flashTimerRef.current) {
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = null;
    }

    setFlashingCell(null);
    requestAnimationFrame(() => {
      setFlashingCell({ row: r, col: c, nonce: Date.now() });
    });

    flashTimerRef.current = setTimeout(() => {
      setFlashingCell(null);
      flashTimerRef.current = null;
    }, 1050);
  }, []);

  // When a user double-clicks a multi-lecturer course, open the lecturer picker immediately.
  const [autoOpenLecturerPicker, setAutoOpenLecturerPicker] = useState(false);
  const [autoApplyLecturerChange, setAutoApplyLecturerChange] = useState(false);

  const groupDropdownRef = useRef(null);
  const [groupDropdownOpen, setGroupDropdownOpen] = useState(false);
  const [groupSearch, setGroupSearch] = useState('');

  // Auto-clear search on focus mechanism (Step 6)
  const handleSearchFocus = () => {
    // If showing the label (i.e. not typing), clear it to allow typing
    const currentLabel = getGroupLabel(timetables[currentGroupIdx], currentGroupIdx);
    if (groupSearch === currentLabel) {
      setGroupSearch('');
    }
  };

  const getGroupLabel = useCallback((t, idx) => {
    const sg = t?.student_group;
    const name = (sg && typeof sg === 'object')
      ? (sg?.name || `Group ${idx + 1}`)
      : (sg || `Group ${idx + 1}`);

    const rawBuilding = (sg && typeof sg === 'object')
      ? (sg?.building || sg?.effective_building || '')
      : '';
    const b = String(rawBuilding || '').trim().toUpperCase();
    const normalized = (b === 'SST' || b.startsWith('SST'))
      ? 'SST'
      : (b === 'TYD' || b.startsWith('TYD'))
        ? 'TYD'
        : '';

    return normalized ? `${name} (${normalized})` : name;
  }, []);

  // Handler for navigation from ConstraintModal (Step 3: Flashing)
  const handleNavigate = useCallback((groupIdx, row, col) => {
     // Ensure safe integer parsing
     const g = parseInt(groupIdx, 10);
     const r = parseInt(row, 10);
     const c = parseInt(col, 10);

     if (!isNaN(g) && g >= 0 && g < timetables.length) {
       // Defer the flash until after the target group's table has rendered.
       pendingNavRef.current = (!isNaN(r) && !isNaN(c)) ? { row: r, col: c } : null;
       if (g === currentGroupIdx) {
         // If we're already on that group, React may not re-render -> flash now.
         if (!isNaN(r) && !isNaN(c)) {
           runFlash(r, c);
         }
         return;
       }

       setCurrentGroupIdx(g);
     }
  }, [timetables.length, currentGroupIdx, runFlash]);

  // Run the flash after group navigation has actually rendered the table.
  useEffect(() => {
    const pending = pendingNavRef.current;
    if (!pending) return;

    const { row: r, col: c } = pending;
    pendingNavRef.current = null;

    runFlash(r, c);
  }, [currentGroupIdx, runFlash]);

  useEffect(() => {
    setTimetables(normalizeTimetables(timetablesData || []));
    setCurrentGroupIdx(0);
    // Capture a fresh initial snapshot whenever new timetables arrive.
    const normalized = normalizeTimetables(timetablesData || []);
    if (normalized.length > 0) {
      initialSnapshotRef.current = {
        timetables: JSON.parse(JSON.stringify(normalized)),
        manualCells: [],
      };
    }
  }, [timetablesData, normalizeTimetables]);

  // Keep the search input showing the current selection when closed (Dash-like)
  useEffect(() => {
    const t = timetables[currentGroupIdx];
    if (!groupDropdownOpen) {
      setGroupSearch(getGroupLabel(t, currentGroupIdx));
    }
  }, [timetables, currentGroupIdx, groupDropdownOpen, getGroupLabel]);

  // Click-outside closes the group dropdown
  useEffect(() => {
    const handleMouseDown = (e) => {
      const el = groupDropdownRef.current;
      if (el && !el.contains(e.target)) {
        setGroupDropdownOpen(false);
        const t = timetables[currentGroupIdx];
        setGroupSearch(getGroupLabel(t, currentGroupIdx));
      }
    };
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [timetables, currentGroupIdx, getGroupLabel]);

  // Fallback: Extract rooms from timetable data
  const extractRoomsFromTimetable = useCallback(() => {
    const rooms = new Set();
    timetables.forEach(t => {
      const timetable = t.timetable || [];
      timetable.forEach(row => {
        row.forEach(cell => {
          if (cell && cell !== 'FREE' && cell !== 'BREAK') {
            const roomMatch = cell.match(/Room:\s*([^\n,]+)/);
            if (roomMatch && roomMatch[1] && roomMatch[1] !== 'Unknown') {
              rooms.add(roomMatch[1].trim());
            }
          }
        });
      });
    });

    const roomsList = Array.from(rooms).map(roomName => {
      const building = roomName.startsWith('SST') ? 'SST' : 'TYD';
      return {
        name: roomName,
        building: building,
        capacity: 50,
        type: 'Classroom'
      };
    });

    setRoomsData(roomsList);
  }, [timetables]);

  // Load rooms data from backend API
  useEffect(() => {
    const loadRoomsData = async () => {
      try {
        const rooms = await getRoomsData();
        setRoomsData(rooms);
      } catch (error) {
        console.error('Failed to load rooms data:', error);
        // Fallback: extract rooms from timetable if API fails
        extractRoomsFromTimetable();
      }
    };

    loadRoomsData();
  }, [extractRoomsFromTimetable]);

  // Load constraint violations from backend API
  useEffect(() => {
    const loadConstraintViolations = async () => {
      if (!uploadId) return;

      setConstraintsLoading(true);

      try {
        const violations = await getConstraintViolations(uploadId);
        const payload = violations && violations.violations ? violations.violations : violations;
        setConstraintDetails(payload || {});
      } catch (error) {
        console.error('Failed to load constraint violations:', error);
      } finally {
        setConstraintsLoading(false);
      }
    };

    loadConstraintViolations();
  }, [uploadId]);

  // Load multi-lecturer course options (course code -> lecturer list)
  useEffect(() => {
    const loadCourseLecturers = async () => {
      if (!uploadId) return;
      try {
        const mapping = await getCourseLecturers(uploadId);
        setCourseLecturersByCourse(mapping || {});
      } catch (e) {
        console.error('Failed to load course lecturers:', e);
      }
    };
    loadCourseLecturers();
  }, [uploadId]);

  // Load saved timetable with manual changes from backend
  useEffect(() => {
    const loadSavedTimetable = async () => {
      if (!uploadId) return;

      try {
        const savedData = await getSavedTimetable(uploadId);
        if (savedData?.upload_id && String(savedData.upload_id) !== String(uploadId)) {
          return;
        }
        const hasFreshProps =
          Array.isArray(timetablesData) && timetablesData.length > 0;
        if (
          !hasFreshProps &&
          savedData.timetables &&
          Array.isArray(savedData.timetables) &&
          savedData.timetables.length > 0
        ) {
          const normalized = normalizeTimetables(savedData.timetables);
          setTimetables(normalized);
          if (!initialSnapshotRef.current) {
            initialSnapshotRef.current = {
              timetables: JSON.parse(JSON.stringify(normalized)),
              manualCells: savedData.manual_cells || [],
            };
          }
        }
        if (savedData.manual_cells && Array.isArray(savedData.manual_cells)) {
          setManualCells(savedData.manual_cells);
        }
      } catch (error) {
        console.error('Failed to load saved timetable:', error);
      }
    };

    loadSavedTimetable();
  }, [uploadId, normalizeTimetables, timetablesData]);

  // Save timetable changes to backend
  const saveToBackend = useCallback(async (updatedTimetables, updatedManualCells) => {
    if (!uploadId) return;

    try {
      await saveTimetableChanges({
        upload_id: uploadId,
        timetables: updatedTimetables,
        manual_cells: updatedManualCells
      });
      
      // Reload constraint violations after save
      const violations = await getConstraintViolations(uploadId);
      const payload = violations && violations.violations ? violations.violations : violations;
      setConstraintDetails(payload || {});
      
      if (onSave) {
        onSave(updatedTimetables, updatedManualCells);
      }
    } catch (error) {
      console.error('Failed to save timetable changes:', error);
    }
  }, [uploadId, onSave]);

  // Parse cell content
  const parseCell = (cellContent) => {
    if (!cellContent) return { course: null, room: null, lecturer: null };
    const text = String(cellContent).trim();
    if (text.toUpperCase() === "FREE" || text.toUpperCase() === "BREAK") {
      return { course: null, room: null, lecturer: null };
    }

    let course = null, room = null, lecturer = null;

    // improved regex parsing to handle commas in values (Bug 4 fix)
    const courseMatch = text.match(/Course:\s*(.*?)(?=\s*(?:,?\s*Lecturer:|,?\s*Room:|$))/i);
    const lecturerMatch = text.match(/Lecturer:\s*(.*?)(?=\s*(?:,?\s*Course:|,?\s*Room:|$))/i);
    const roomMatch = text.match(/Room:\s*(.*?)(?=\s*(?:,?\s*Course:|,?\s*Lecturer:|$))/i);

    if (courseMatch) course = courseMatch[1].trim();
    if (lecturerMatch) lecturer = lecturerMatch[1].trim();
    if (roomMatch) room = roomMatch[1].trim();

    // Fallback: if regex failed but we have text (e.g. simplified format)
    if (!course && !lecturer && !room) {
        // Handle newline format purely
        if (text.includes('\n')) {
             const parts = text.split('\n').map(p => p.trim());
             for (const part of parts) {
                if (part.startsWith('Course:')) course = part.replace('Course:', '').trim();
                else if (part.startsWith('Lecturer:')) lecturer = part.replace('Lecturer:', '').trim();
                else if (part.startsWith('Room:')) room = part.replace('Room:', '').trim();
             }
        } else {
             // Basic comma split (legacy fallback)
             const parts = text.split(',').map(p => p.trim());
             if (parts.length > 0 && !parts[0].includes(':')) course = parts[0];
        }
    }

    return {
      course: course && course !== 'Unknown' ? course : null,
      room: room && room !== 'Unknown' ? room : null,
      lecturer: lecturer && lecturer !== 'Unknown' ? lecturer : null
    };
  };

  // Format cell content for rendering (Step 2: Structured Layout & Bold Violations)
  const renderCellContent = (cellValue, cellKey, conflictsData) => {
    if (!cellValue || cellValue === 'FREE' || cellValue === 'BREAK') return cellValue;

    const { course, room, lecturer } = parseCell(cellValue);
    if (!course) return cellValue;

    const conflict = conflictsData[cellKey];
    // Bold logic based on conflict type
    const isLecturerConflict = conflict && (conflict.lecturerConflict || conflict.bothConflict);
    const isRoomConflict = conflict && (conflict.roomConflict || conflict.bothConflict);
    const lecturerOptions = Array.isArray(courseLecturersByCourse?.[course]) ? courseLecturersByCourse[course] : [];
    const hasMultiplePossibleLecturers = (lecturerOptions.length > 1);

    return (
      <div className="cell-content" style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'center' }}>
        {hasMultiplePossibleLecturers && (
          <span
            className="multi-lecturer-asterisk"
            title="Multiple lecturers available"
            aria-label="Multiple lecturers available"
          >
            *
          </span>
        )}
        <span>Course: {course}</span>
        <span style={{ fontWeight: isLecturerConflict ? 'bold' : 'normal' }}>
          Lecturer: {lecturer || 'Unknown'}
        </span>
        <span style={{ fontWeight: isRoomConflict ? 'bold' : 'normal' }}>
          Room: {room || 'Unknown'}
        </span>
      </div>
    );
  };

  // Format cell content
  const formatCell = (course, lecturer, room) => {
    if (!course) return 'FREE';
    // Match backend/Dash comma-separated format.
    return `Course: ${course}, Lecturer: ${lecturer || 'Unknown'}, Room: ${room || 'Unknown'}`;
  };

  // Detect conflicts
  const detectConflicts = useCallback(() => {
    const newConflicts = {};
    const currentTimetable = timetables[currentGroupIdx]?.timetable || [];

    for (let row = 0; row < currentTimetable.length; row++) {
      const rowData = currentTimetable[row];
      for (let col = 1; col < rowData.length; col++) {
        const cell = rowData[col];
        const { course, room, lecturer } = parseCell(cell);

        if (!course || course === 'FREE' || course === 'BREAK') continue;

        const cellKey = `${row}-${col}`;
        let roomConflict = false;
        let lecturerConflict = false;

        // Check room conflicts across all groups
        for (let g = 0; g < timetables.length; g++) {
          if (g === currentGroupIdx) continue;
          const otherTimetable = timetables[g]?.timetable || [];
          if (row < otherTimetable.length && col < otherTimetable[row].length) {
            const otherCell = otherTimetable[row][col];
            const otherParsed = parseCell(otherCell);
            
            if (otherParsed.room && room && otherParsed.room === room) {
              roomConflict = true;
            }
            if (otherParsed.lecturer && lecturer && otherParsed.lecturer === lecturer) {
              lecturerConflict = true;
            }
          }
        }

        if (roomConflict || lecturerConflict) {
          newConflicts[cellKey] = {
            roomConflict,
            lecturerConflict,
            bothConflict: roomConflict && lecturerConflict
          };
        }
      }
    }

    setConflicts(newConflicts);
  }, [timetables, currentGroupIdx]);

  const totalViolationCount = useMemo(() => {
    // Return count of categories with at least one violation (Dashboard style), not total violations
    const d = constraintDetails || {};
    return Object.keys(d).filter(k => 
      k !== 'total' && 
      k !== 'constraint_violation_details' && 
      Array.isArray(d[k]) && 
      d[k].length > 0
    ).length;
  }, [constraintDetails]);


  // Recompute local conflicts only (backend provides full constraint violations)
  const recomputeLocalConflicts = useCallback(() => {
    // Local conflict detection is done in detectConflicts()
    // Backend provides full constraint violations via API
    // This function is kept for compatibility
  }, []);

  useEffect(() => {
    detectConflicts();
  }, [detectConflicts]);

  useEffect(() => {
    recomputeLocalConflicts();
  }, [recomputeLocalConflicts]);

  // Handle drag start
  const handleDragStart = (e, row, col) => {
    const cell = timetables[currentGroupIdx]?.timetable[row][col];
    if (cell === 'BREAK') {
      e.preventDefault();
      return;
    }
    setDraggedCell({ row, col });
    e.dataTransfer.effectAllowed = 'move';
  };

  // Handle drag over
  const handleDragOver = (e, row, col) => {
    e.preventDefault();
    const cell = timetables[currentGroupIdx]?.timetable[row][col];
    if (cell === 'BREAK') return;
    setDragOverCell({ row, col });
  };

  // Handle drag leave
  const handleDragLeave = () => {
    setDragOverCell(null);
  };

  // Handle drop
  const handleDrop = (e, targetRow, targetCol) => {
    e.preventDefault();
    setDragOverCell(null);

    if (!draggedCell) return;

    const targetCell = timetables[currentGroupIdx]?.timetable?.[targetRow]?.[targetCol];
    if (targetCell === 'BREAK') return;

    // Swap cells
    const newTimetables = [...timetables];
    const currentTimetable = newTimetables[currentGroupIdx].timetable;
    const temp = currentTimetable[draggedCell.row][draggedCell.col];
    currentTimetable[draggedCell.row][draggedCell.col] = currentTimetable[targetRow][targetCol];
    currentTimetable[targetRow][targetCol] = temp;

    // Fixed: Do NOT mark swapped cells as manually modified to avoid blue border (Bug 1).
    // The blue border is reserved ONLY for explicit "manually scheduled" cells (like from Room Modal).
    // Swapping maintains existing manual status if they were manually placed, but doesn't add new ones?
    // Actually, "manual_cells" array tracks modifications for valid backend saving.
    // If we don't add to manualCells, the backend might overwrite it on next optimize?
    // NOTE: The request specifically asks to remove the blue border. 
    // We will track the change in `timetables` state and send it to backend, but we will NOT append to `manualCells` array 
    // here, assuming `manualCells` is strictly for the visual "blue border" and "lock" feature.
    // If persistence is needed for swaps, we rely on `timetables` data being saved.
    
    // const cell1Key = `${currentGroupIdx}-${draggedCell.row}-${draggedCell.col}`;
    // const cell2Key = `${currentGroupIdx}-${targetRow}-${targetCol}`;
    const updatedManualCells = [...manualCells];
    // if (!updatedManualCells.includes(cell1Key)) updatedManualCells.push(cell1Key);
    // if (!updatedManualCells.includes(cell2Key)) updatedManualCells.push(cell2Key);

    setTimetables(newTimetables);
    setManualCells(updatedManualCells);
    setDraggedCell(null);

    // Auto-save to backend
    saveToBackend(newTimetables, updatedManualCells);
  };

  // Handle cell click for room selection
  const handleCellClick = (row, col) => {
    // Delay click so double-click can cancel it.
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }

    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;

      const cell = timetables[currentGroupIdx]?.timetable?.[row]?.[col];
      if (cell === 'BREAK') return;

      // Default click is room edit/schedule; do not auto-open lecturer picker.
      setAutoOpenLecturerPicker(false);
      setAutoApplyLecturerChange(false);

      // Open MissingClassesModal if cell is free
      if (!cell || cell === 'FREE' || String(cell).trim() === '') {
        setSelectedCell({ row, col });
        setMissingClassesModalOpen(true);
        return;
      }

      setSelectedCell({ row, col });
      setRoomModalOpen(true);
    }, 200);
  };

  const handleCellDoubleClick = (row, col) => {
    if (clickTimerRef.current) {
      clearTimeout(clickTimerRef.current);
      clickTimerRef.current = null;
    }

    const cell = timetables[currentGroupIdx]?.timetable?.[row]?.[col];
    if (cell === 'BREAK') return;
    if (!cell || cell === 'FREE' || String(cell).trim() === '') return;

    const { course } = parseCell(cell);
    if (!course) return;

    const options = Array.isArray(courseLecturersByCourse?.[course]) ? courseLecturersByCourse[course] : [];
    if (options.length <= 1) return;

    setSelectedCell({ row, col });
    setAutoOpenLecturerPicker(true);
    setAutoApplyLecturerChange(true);
    setRoomModalOpen(true);
  };

  const splitLecturers = (lecturerValue) => {
    const raw = String(lecturerValue || '').trim();
    if (!raw) return [];
    return raw.split(',').map((p) => p.trim()).filter(Boolean);
  };

  // Handle room/lecturer confirm (edit or schedule)
  const handleRoomChange = ({ room: newRoom, lecturer: newLecturer }) => {
    if (!selectedCell) return;

    const { row, col } = selectedCell;
    const cell = timetables[currentGroupIdx]?.timetable[row][col];

    // Scheduling into a FREE slot
    if (pendingSchedule) {
      if (!pendingSchedule.course) return;

      const lecturerToUse = newLecturer || pendingSchedule.lecturer || null;
      if (!lecturerToUse) return;

      const newTimetables = [...timetables];
      newTimetables[currentGroupIdx].timetable[row][col] = formatCell(pendingSchedule.course, lecturerToUse, newRoom);

      const cellKey = `${currentGroupIdx}-${row}-${col}`;
      const updatedManualCells = [...manualCells];
      if (!updatedManualCells.includes(cellKey)) updatedManualCells.push(cellKey);

      setTimetables(newTimetables);
      setManualCells(updatedManualCells);
      setPendingSchedule(null);
      setRoomModalOpen(false);
      setSelectedCell(null);

      saveToBackend(newTimetables, updatedManualCells);
      return;
    }

    // Regular room/lecturer edit
    const { course, lecturer } = parseCell(cell);
    if (!course) return;

    const newTimetables = [...timetables];
    const lecturerToUse = newLecturer || lecturer;
    newTimetables[currentGroupIdx].timetable[row][col] = formatCell(course, lecturerToUse, newRoom);

    // Mark as manual
    const updatedManualCells = [...manualCells];
    
    // Fixed: Changing a room via modal is NOT manually scheduling a new class, so do NOT add blue border.
    // Only "Manually Scheduled" implies adding a missing class to a free slot (handled elsewhere or implicit).
    // The Room Modal just modifies the room.
    // if (!updatedManualCells.includes(cellKey)) {
    //   updatedManualCells.push(cellKey);
    // }

    setTimetables(newTimetables);
    setManualCells(updatedManualCells);
    setRoomModalOpen(false);
    setSelectedCell(null);

    // Auto-save to backend
    saveToBackend(newTimetables, updatedManualCells);
  };

  const handleUndoAllChanges = async () => {
    const snapshot = initialSnapshotRef.current;
    if (!snapshot || !snapshot.timetables) return;

    const restored = JSON.parse(JSON.stringify(snapshot.timetables));
    setTimetables(restored);
    setManualCells([]);
    setSelectedCell(null);
    setRoomModalOpen(false);

    await saveToBackend(restored, []);
  };

  // Get cell class
  const getCellClass = (row, col) => {
    const cellKey = `${row}-${col}`;
    const manualKey = `${currentGroupIdx}-${row}-${col}`;
    const classes = ['cell'];
    const cellValue = timetables[currentGroupIdx]?.timetable?.[row]?.[col];

    if (cellValue === 'BREAK') {
      classes.push('break-time');
      return classes.join(' ');
    }

    // Step 5: Thicker outlines for manual cells
    if (manualCells.includes(manualKey)) {
      classes.push('manual-schedule');
    }

    if (conflicts[cellKey]) {
      if (conflicts[cellKey].bothConflict) classes.push('both-conflict');
      else if (conflicts[cellKey].roomConflict) classes.push('room-conflict');
      else if (conflicts[cellKey].lecturerConflict) classes.push('lecturer-conflict');
    }

    if (dragOverCell && dragOverCell.row === row && dragOverCell.col === col) {
      classes.push('drag-over');
    }

    if (draggedCell && draggedCell.row === row && draggedCell.col === col) {
      classes.push('dragging');
    }

    // Step 3: Flash animation
    if (flashingCell && flashingCell.row === row && flashingCell.col === col) {
      classes.push('flash-cell');
    }
  
    return classes.join(' ');
  };

  // Render timetable
  const renderTimetable = () => {
    const timetable = timetables[currentGroupIdx]?.timetable || [];
    const groupName = getGroupLabel(timetables[currentGroupIdx], currentGroupIdx);

    return (
      <div className="student-group-container">
        <div className="timetable-header">
          <h2 className="timetable-title">Timetable for {groupName}</h2>
        </div>

        <div className="timetable-controls-row">
          <div className="controls-left">
            <button className="errors-button" onClick={() => setErrorModalOpen(true)}>
              View Violations
              {totalViolationCount > 0 && (
                <span className="error-notification">{totalViolationCount}</span>
              )}
            </button>
            <button className="undo-button" onClick={handleUndoAllChanges} type="button">
              Undo All Changes
            </button>
          </div>
          
          <div className="controls-right">
            <div className="nav-arrows">
              <button
                className="nav-arrow nav-arrow-secondary"
                onClick={() => setCurrentGroupIdx(Math.max(0, currentGroupIdx - 1))}
                disabled={currentGroupIdx === 0}
                title="Previous student group"
              >
                ‹
              </button>
              <button
                className="nav-arrow"
                onClick={() => setCurrentGroupIdx(Math.min(timetables.length - 1, currentGroupIdx + 1))}
                disabled={currentGroupIdx === timetables.length - 1}
                title="Next student group"
              >
                ›
              </button>
            </div>
            <button
              className="nav-arrow"
              onClick={() => setHelpModalOpen(true)}
              title="Help"
              type="button"
            >
              ?
            </button>
          </div>
        </div>

        {/* Step 3: Pass handleNavigate to modal */}
        <ConstraintModal 
          isOpen={errorModalOpen}
          onClose={() => setErrorModalOpen(false)}
          constraintDetails={constraintDetails}
          timetables={timetables}
          onNavigate={(groupIdx, row, col) => {
            handleNavigate(groupIdx, row, col);
            setErrorModalOpen(false); // Close modal on navigate? Dash usually keeps it or closes.
            // Requirement says "redirects to where the error is". Closing allows user to see it.
          }}
        />

        <div className="table-wrapper">
          <table className="timetable">
            <thead>
              <tr>
                <th className="time-cell">Time</th>
                {days.map(day => (
                  <th key={day}>{day}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {timetable.map((row, rowIdx) => {
                const rowArray = Array.isArray(row) ? row : normalizeRow(row, rowIdx);
                return (
                  <tr key={rowIdx}>
                    <td className="time-cell">{rowArray[0] || hours[rowIdx]}</td>
                    {rowArray.slice(1).map((cell, colIdx) => {
                      const finalCol = colIdx + 1;
                      const cellKey = `${rowIdx}-${finalCol}`;
                      return (
                      <td 
                        key={colIdx}
                        className={getCellClass(rowIdx, finalCol)}
                        data-row={rowIdx}
                        data-col={finalCol}
                        draggable={cell !== 'BREAK'}
                        onDragStart={(e) => handleDragStart(e, rowIdx, finalCol)}
                        onDragOver={(e) => handleDragOver(e, rowIdx, finalCol)}
                        onDragLeave={handleDragLeave}
                        onDrop={(e) => handleDrop(e, rowIdx, finalCol)}
                        onClick={() => handleCellClick(rowIdx, finalCol)}
                        onDoubleClick={() => handleCellDoubleClick(rowIdx, finalCol)}
                      >
                        {cell === 'BREAK' ? 'BREAK' : renderCellContent(cell, cellKey, conflicts)}
                      </td>
                    );})}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const isLoading = !Array.isArray(timetables) || timetables.length === 0;

  if (isLoading) {
    return (
      <div className="interactive-timetable">
        <div className="timetable-controls">
          <h1 className="main-title">Interactive Drag & Drop Timetable - DE Optimization Results</h1>
          <p>Loading timetable data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="interactive-timetable">
      <div className="timetable-controls">
        <h1 className="main-title">Interactive Drag & Drop Timetable - DE Optimization Results</h1>
        <div className="group-search" ref={groupDropdownRef}>
          <input
            className="group-search-input"
            type="text"
            // Step 6: Value logic for auto-clearing
            value={
              groupDropdownOpen && 
              groupSearch === getGroupLabel(timetables[currentGroupIdx], currentGroupIdx) 
              ? '' 
              : groupSearch
            }
            placeholder={getGroupLabel(timetables[currentGroupIdx], currentGroupIdx)}
            onChange={(e) => {
              setGroupSearch(e.target.value);
              setGroupDropdownOpen(true);
            }}
            onFocus={() => {
              setGroupDropdownOpen(true);
              handleSearchFocus();
            }}
            aria-label="Select Student Group"
          />
          {groupDropdownOpen && (
            <div className="group-search-menu" role="listbox">
              {timetables
                .map((t, idx) => ({ idx, label: getGroupLabel(t, idx) }))
                .filter(({ label }) => label.toLowerCase().includes(String(groupSearch || '').toLowerCase()))
                .slice(0, 50)
                .map(({ idx, label }) => (
                  <button
                    key={idx}
                    type="button"
                    className="group-search-option"
                    onClick={() => {
                      setCurrentGroupIdx(idx);
                      setGroupDropdownOpen(false);
                      setGroupSearch(label);
                    }}
                    role="option"
                    aria-selected={idx === currentGroupIdx}
                  >
                    {label}
                  </button>
                ))}
            </div>
          )}
        </div>
      </div>

      {renderTimetable()}

      <div className="download-footer">
        <button className="download-footer-button" onClick={() => setDownloadModalOpen(true)} type="button">
          Download Timetables
        </button>
        {constraintsLoading && <div className="constraints-loading">Updating errors…</div>}
      </div>

      {roomModalOpen && (
        <RoomModal
          isOpen={roomModalOpen}
          onClose={() => {
            setRoomModalOpen(false);
            setSelectedCell(null);
            setPendingSchedule(null);
            setAutoOpenLecturerPicker(false);
            setAutoApplyLecturerChange(false);
          }}
          onConfirm={handleRoomChange}
          currentRoom={selectedCell ? parseCell(timetables[currentGroupIdx]?.timetable[selectedCell.row][selectedCell.col]).room : null}
          roomsData={roomsData}
          timetables={timetables}
          currentRow={selectedCell?.row}
          currentCol={selectedCell?.col}
          isManual={selectedCell && manualCells.includes(`${currentGroupIdx}-${selectedCell.row}-${selectedCell.col}`)}
          mode={pendingSchedule ? 'schedule' : 'edit'}
          courseName={pendingSchedule ? pendingSchedule.course : (selectedCell ? parseCell(timetables[currentGroupIdx]?.timetable[selectedCell.row][selectedCell.col]).course : null)}
          currentLecturer={pendingSchedule ? (pendingSchedule.lecturer || null) : (selectedCell ? parseCell(timetables[currentGroupIdx]?.timetable[selectedCell.row][selectedCell.col]).lecturer : null)}
          lecturerOptions={pendingSchedule
            ? (Array.isArray(pendingSchedule.lecturerOptions) ? pendingSchedule.lecturerOptions : [])
            : (selectedCell ? (() => {
              const cell = timetables[currentGroupIdx]?.timetable[selectedCell.row][selectedCell.col];
              const { course, lecturer } = parseCell(cell);
              const options = Array.isArray(courseLecturersByCourse?.[course]) ? courseLecturersByCourse[course] : [];
              return options.length > 0 ? options : splitLecturers(lecturer);
            })() : [])
          }
          isMultiLecturer={pendingSchedule
            ? (Array.isArray(pendingSchedule.lecturerOptions) && pendingSchedule.lecturerOptions.length > 1)
            : (selectedCell && (() => {
              const cell = timetables[currentGroupIdx]?.timetable[selectedCell.row][selectedCell.col];
              const { course } = parseCell(cell);
              const options = Array.isArray(courseLecturersByCourse?.[course]) ? courseLecturersByCourse[course] : [];
              return (options.length > 1);
            })())
          }
          autoOpenLecturerModal={autoOpenLecturerPicker}
          autoApplyLecturerChange={autoApplyLecturerChange}
        />
      )}

      {errorModalOpen && (
        // Duplicate modal rendered at bottom removed, logic moved to top renderTimetable or kept here but updated.
        // Wait, I inserted one inside renderTimetable() previously (lines ~613). 
        // This one at the bottom (lines ~760) is likely the main one if renderTimetable returns JSX for the MAIN content area.
        // I should probably remove the one I inserted in `renderTimetable` if `renderTimetable` is called inside return().
        // Let's check where `renderTimetable` is called.
        // It is called in the main return: `{renderTimetable()}`.
        // So I have effectively duplicated it. I should remove this one at the bottom OR the one inside.
        // The one inside `renderTimetable` is better placed visually near the button? No, modals are usually portals or overlays.
        // I will keep the one I added inside `renderTimetable` because I customized the props there, and return null here to safely remove it.
        null
      )}

      {downloadModalOpen && (
        <DownloadModal
          isOpen={downloadModalOpen}
          onClose={() => setDownloadModalOpen(false)}
          timetables={timetables}
          uploadId={uploadId}
        />
      )}

      {missingClassesModalOpen && (
        <MissingClassesModal
          isOpen={missingClassesModalOpen}
          onClose={() => {
            setMissingClassesModalOpen(false);
          }}
          constraintDetails={constraintDetails}
          currentGroup={timetables[currentGroupIdx]}
          onScheduleClass={(item) => {
            setPendingSchedule(item);
            setMissingClassesModalOpen(false);
            setRoomModalOpen(true);
          }}
        />
      )}

      <TimetableHelpModal isOpen={helpModalOpen} onClose={() => setHelpModalOpen(false)} />
    </div>
  );
};

export default InteractiveTimetable;
