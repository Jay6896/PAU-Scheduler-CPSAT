import React, { useMemo, useState } from 'react';
import './ConstraintModal.css';

const ConstraintModal = ({ isOpen, onClose, constraintDetails, timetables, onNavigate }) => {
  // Dash allows multiple dropdowns expanded at once.
  const [expandedConstraints, setExpandedConstraints] = useState(() => new Set());

  // Mapping from user-friendly names to internal names (SEPT 13 format)
  const constraintMapping = {
    'Same Student Group Overlaps': 'Same Student Group Overlaps',
    'Different Student Group Overlaps': 'Different Student Group Overlaps',
    'Lecturer Clashes': 'Lecturer Clashes',
    'Lecturer Schedule Conflicts (Day/Time)': 'Lecturer Schedule Conflicts (Day/Time)',
    'Lecturer Workload Violations': 'Lecturer Workload Violations',
    'Consecutive Slot Violations': 'Consecutive Slot Violations',
    'Missing or Extra Classes': 'Missing or Extra Classes',
    'Same Course in Multiple Rooms on Same Day': 'Same Course in Multiple Rooms on Same Day',
    'Room Capacity/Type Conflicts': 'Room Capacity/Type Conflicts',
    'Classes During Break Time': 'Classes During Break Time',
    'Late Classes': 'Late Classes',
    'Course Spread': 'Spread Events Violations'
  };

  const groupMap = useMemo(() => {
    const map = new Map();
    (timetables || []).forEach((t, idx) => {
      const g = t?.student_group;
      const name = (g && typeof g === 'object') ? g.name : g;
      if (name) map.set(String(name), idx);
    });
    return map;
  }, [timetables]);

  const extractCourseFromCell = (cellContent) => {
    if (!cellContent) return null;
    const text = String(cellContent).trim();
    if (!text || text.toUpperCase() === 'FREE' || text.toUpperCase() === 'BREAK') return null;

    // Multi-line: first line is usually the course code
    if (text.includes('\n')) {
      const first = text.split('\n').map(s => s.trim()).filter(Boolean)[0];
      return first || null;
    }

    // Inline: "Course: XXX" format
    const m = text.match(/Course:\s*([^,]+)(?:,|$)/i);
    if (m && m[1]) return String(m[1]).trim();

    // Fallback: assume first token is course code
    const token = text.split(/\s+/)[0];
    return token || null;
  };

  const parseStartTimeFromRowLabel = (label, rowIdx) => {
    // Expected: "08:30 - 09:30" or "08:30-09:30" or just "08:30"
    if (label) {
      const s = String(label);
      const m = s.match(/(\d{1,2}:\d{2})/);
      if (m && m[1]) return m[1];
    }
    // Fallback to 08:30 + rowIdx hours
    const baseMinutes = 8 * 60 + 30;
    const minutes = baseMinutes + (rowIdx * 60);
    const hh = Math.floor(minutes / 60);
    const mm = minutes % 60;
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  };

  const findCourseOccurrences = (groupName, courseCode) => {
    if (!groupName || !courseCode) return [];
    const idx = groupMap.has(String(groupName)) ? groupMap.get(String(groupName)) : null;
    if (idx === null || idx === undefined) return [];
    const grid = timetables?.[idx]?.timetable;
    if (!Array.isArray(grid)) return [];

    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
    const out = [];

    for (let r = 0; r < grid.length; r++) {
      const row = grid[r];
      if (!Array.isArray(row) || row.length < 2) continue;

      const startTime = parseStartTimeFromRowLabel(row[0], r);

      for (let d = 0; d < Math.min(5, row.length - 1); d++) {
        const cell = row[d + 1];
        const cellCourse = extractCourseFromCell(cell);
        if (!cellCourse) continue;
        if (String(cellCourse).trim().toUpperCase() !== String(courseCode).trim().toUpperCase()) continue;

        out.push({
          row: r,
          col: d + 1,
          day: days[d],
          time: startTime
        });
      }
    }

    return out;
  };

  if (!isOpen) return null;

  const toggleConstraint = (constraintName) => {
    setExpandedConstraints(prev => {
      const next = new Set(prev);
      if (next.has(constraintName)) next.delete(constraintName);
      else next.add(constraintName);
      return next;
    });
  };

  const findTargetGroupIdx = (internalName, violation) => {
    if (!violation || typeof violation !== 'object') return null;

    if (internalName === 'Same Student Group Overlaps') {
      return groupMap.has(violation.group) ? groupMap.get(violation.group) : null;
    }

    if (internalName === 'Different Student Group Overlaps') {
      if (Array.isArray(violation.events) && violation.events.length > 0) {
        const match = /Group:\s*'([^']+)'/i.exec(String(violation.events[0]));
        if (match && groupMap.has(match[1])) return groupMap.get(match[1]);
      }
      if (Array.isArray(violation.groups) && violation.groups.length > 0) {
        return groupMap.has(violation.groups[0]) ? groupMap.get(violation.groups[0]) : null;
      }
      return null;
    }

    if (internalName === 'Lecturer Clashes') {
      if (Array.isArray(violation.groups) && violation.groups.length > 0) {
        return groupMap.has(violation.groups[0]) ? groupMap.get(violation.groups[0]) : null;
      }
      return null;
    }

    if (
      internalName === 'Lecturer Schedule Conflicts (Day/Time)' ||
      internalName === 'Consecutive Slot Violations' ||
      internalName === 'Missing or Extra Classes' ||
      internalName === 'Same Course in Multiple Rooms on Same Day' ||
      internalName === 'Room Capacity/Type Conflicts' ||
      internalName === 'Classes During Break Time' ||
      internalName === 'Late Classes' ||
      internalName === 'Spread Events Violations'
    ) {
      return groupMap.has(violation.group) ? groupMap.get(violation.group) : null;
    }

    return null;
  };

  const buildItemText = (internalName, violation) => {
    if (!violation) return '';
    if (typeof violation === 'string') return violation;
    if (typeof violation !== 'object') return String(violation);

    if (internalName === 'Same Student Group Overlaps') {
      const courses = Array.isArray(violation.courses) ? violation.courses.join(', ') : String(violation.courses || '');
      return `Group '${violation.group}' has clashing courses ${courses} on ${violation.location}`;
    }

    if (internalName === 'Different Student Group Overlaps') {
      if (Array.isArray(violation.events)) {
        const events = violation.events.join(', ');
        return `Room conflict at ${violation.location}: ${events}`;
      }
      if (Array.isArray(violation.groups)) {
        return `Room conflict in ${violation.room} at ${violation.location}: Groups ${violation.groups.join(', ')} both scheduled`;
      }
      return `Room conflict at ${violation.location || 'Unknown location'}`;
    }

    if (internalName === 'Lecturer Clashes') {
      if (Array.isArray(violation.groups) && violation.groups.length >= 2) {
        return `Lecturer '${violation.lecturer}' has clashing courses ${violation.courses?.[0]} for group ${violation.groups?.[0]}, and ${violation.courses?.[1]} for group ${violation.groups?.[1]} on ${violation.location}`;
      }
      const courses = Array.isArray(violation.courses) ? violation.courses.join(', ') : String(violation.courses || '');
      return `Lecturer '${violation.lecturer}' has clashing courses ${courses} on ${violation.location}`;
    }

    if (internalName === 'Lecturer Schedule Conflicts (Day/Time)') {
      let locDisplay = violation.location || '';
      if (violation.day && violation.time) {
        locDisplay = `${violation.day} at ${violation.time}`;
      }

      // Display available days
      let availDayDisplay = violation.available_days;
      if (typeof availDayDisplay === 'object' && availDayDisplay !== null) {
        if (Array.isArray(availDayDisplay)) {
          availDayDisplay = availDayDisplay.join(', ');
        } else {
          // Unexpected structure; best-effort flatten
          try {
            availDayDisplay = Object.values(availDayDisplay).flat().join(', ');
          } catch (e) {
            availDayDisplay = String(availDayDisplay);
          }
        }
      }
      if (availDayDisplay == null || String(availDayDisplay).trim() === '') {
        availDayDisplay = 'Not specified';
      }

      // Handle case where available_times is passed as a raw object/array
      let availTimeDisplay = violation.available_times;
      if (typeof availTimeDisplay === 'object' && availTimeDisplay !== null) {
        if (Array.isArray(availTimeDisplay)) {
           availTimeDisplay = availTimeDisplay.join(', ');
        } else {
           // Dictionary case: Try to find times for the specific day
           const d = violation.day || '';
           const dCap = d.charAt(0).toUpperCase() + d.slice(1).toLowerCase();
           
           const val = availTimeDisplay[d] || availTimeDisplay[dCap] || availTimeDisplay['All'];
           
           // If we found a value for the day, use it. Otherwise fallback to flattening all values.
           if (val) {
               availTimeDisplay = Array.isArray(val) ? val.join(', ') : String(val);
           } else {
               const all = Object.values(availTimeDisplay).flat();
               availTimeDisplay = all.join(', ');
           }
        }
      }

      if (availTimeDisplay == null || String(availTimeDisplay).trim() === '') {
        availTimeDisplay = 'Not specified';
      }

      const when = locDisplay || 'Unknown day/time';
      return `Lecturer '${violation.lecturer}' is available on days [${availDayDisplay}] during times [${availTimeDisplay}] but scheduled on ${when}`;
    }

    if (internalName === 'Lecturer Workload Violations') {
      if (violation.type === 'Excessive Daily Hours') {
        const coursesText = violation.courses || 'Unknown courses';
        return `Lecturer '${violation.lecturer}' has ${violation.hours_scheduled} hours on ${violation.day} from courses ${coursesText}, exceeding maximum of ${violation.max_allowed} hours per day`;
      }
      if (violation.type === 'Excessive Consecutive Hours') {
        const coursesText = violation.courses || 'Unknown courses';
        const hoursTimes = Array.isArray(violation.hours_times) ? violation.hours_times.join(', ') : String(violation.hours_times || '');
        return `Lecturer '${violation.lecturer}' has ${violation.consecutive_hours} consecutive hours on ${violation.day} from courses ${coursesText} (${hoursTimes}), exceeding maximum of ${violation.max_allowed} consecutive hours`;
      }
      return `Lecturer workload violation for ${violation.lecturer} on ${violation.day}: ${violation.violation || 'Unknown violation'}`;
    }

    if (internalName === 'Consecutive Slot Violations') {
      const reason = violation.reason || violation.issue || 'Consecutive slot violation';
      const timesVal = violation.times || [];
      const timesStr = (!timesVal || (Array.isArray(timesVal) && timesVal.length === 0))
        ? (violation.location || '')
        : (Array.isArray(timesVal) ? timesVal.join(', ') : String(timesVal));
      
      const courseNameDisplay = violation.course_name ? ` (${violation.course_name})` : '';
      // If backend doesn't supply day info, derive it from the actual timetable grid.
      let dayInfo = violation.day;
      if (!dayInfo && violation.group && violation.course) {
        const occ = findCourseOccurrences(violation.group, violation.course);
        if (occ.length > 0) {
          dayInfo = occ.map(o => `${o.day} ${o.time}`).join(', ');
        }
      }
      return `${reason}: Course '${violation.course || ''}'${courseNameDisplay} for group '${violation.group || ''}'${dayInfo ? ` on ${dayInfo}` : ''} at ${timesStr}`;
    }

    if (internalName === 'Missing or Extra Classes') {
      return `${violation.issue} classes for ${violation.location}: Expected ${violation.expected}, Got ${violation.actual}`;
    }

    if (internalName === 'Same Course in Multiple Rooms on Same Day') {
      const rooms = Array.isArray(violation.rooms) ? violation.rooms.join(', ') : String(violation.rooms || '');
      return `${violation.location} in multiple rooms: ${rooms}`;
    }

    if (internalName === 'Room Capacity/Type Conflicts') {
      if (violation.type === 'Room Type Mismatch') {
        return `Room type mismatch at ${violation.location}: ${violation.course} for group ${violation.group} requires ${violation.required_type} but scheduled in ${violation.room} (${violation.room_type})`;
      }
      if (violation.type === 'Wrong Building (TYD in SST)') {
        return `Wrong Building Constraint: Group '${violation.group}' (Non-SST) is scheduled in SST room '${violation.room}' on ${violation.day} at ${violation.time}`;
      }
      if (violation.students !== undefined && violation.capacity !== undefined) {
        return `Room capacity exceeded at ${violation.room} by group ${violation.group} on ${violation.day} at ${violation.time}: ${violation.students} students in ${violation.room} (capacity: ${violation.capacity})`;
      }
      return `${violation.type} at ${violation.location || 'Unknown'}`;
    }

    if (internalName === 'Classes During Break Time') {
      return `Class during break time at ${violation.location}: ${violation.course} for ${violation.group}`;
    }

    if (internalName === 'Late Classes') {
      const typ = violation.type ? `${violation.type}: ` : '';
      return `${typ}${violation.location || `${violation.course || ''} for ${violation.group || ''}`}`;
    }

    if (internalName === 'Spread Events Violations') {
      const group = violation.group || 'Unknown group';
      const used = violation.days_used ?? '?';
      const target = violation.target_days ?? '?';
      return `${group} has courses on ${used}/${target} days. ${violation.reason || ''}`.trim();
    }

    return JSON.stringify(violation);
  };

  return (
    <>
      <div className="modal-overlay" id="errors-modal-overlay" onClick={onClose}></div>
      <div className="room-selection-modal" id="errors-modal">
        <div className="modal-header">
          <h3 className="modal-title">
            Constraint Violations
          </h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div id="errors-content" className="errors-content">
          {!constraintDetails ? (
            <div style={{ padding: '20px', textAlign: 'center' }}>
              No constraint violation data available.
            </div>
          ) : (
            Object.entries(constraintMapping).map(([displayName, internalName]) => {
              let violations = (constraintDetails && constraintDetails[internalName]) ? constraintDetails[internalName] : [];

              const count = Array.isArray(violations) ? violations.length : 0;
              const isMediumCount = (
                displayName === 'Same Course in Multiple Rooms on Same Day'
                || displayName === 'Consecutive Slot Violations'
                || displayName === 'Course Spread'
              );
              const isExpanded = expandedConstraints.has(displayName);

              return (
                <div key={displayName} className="constraint-dropdown">
                  <div
                    className={`constraint-header ${isExpanded ? 'active' : ''}`}
                    onClick={() => toggleConstraint(displayName)}
                  >
                    <span>{displayName}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className={`constraint-count ${count === 0 ? 'zero' : (isMediumCount ? 'non-zero medium' : 'non-zero')}`}>
                        {count} Occurrence{count !== 1 ? 's' : ''}
                      </span>
                      <span className={`constraint-arrow ${isExpanded ? 'rotated' : ''}`}>
                        ^
                      </span>
                    </div>
                  </div>

                  <div className={`constraint-details ${isExpanded ? 'expanded' : ''}`}>
                    {count === 0 ? (
                      <div className="constraint-item" style={{ color: '#28a745', fontStyle: 'italic' }}>
                        No violations found.
                      </div>
                    ) : (
                      violations.map((violation, idx) => {
                        const targetGroupIdx = findTargetGroupIdx(internalName, violation);
                        const itemText = buildItemText(internalName, violation);
                        const isClickable = targetGroupIdx !== null && targetGroupIdx !== undefined;

                        return (
                          <div
                            key={idx}
                            className={`constraint-item ${isClickable ? 'clickable' : ''}`}
                            title={isClickable ? "Click to view this student group's timetable" : undefined}
                            onClick={() => {
                              if (!isClickable) return;
                              
                              // Attempt to parse day/time for flashing
                              let targetRow = null;
                              let targetCol = null;
                              
                              // Helper to map day/time
                              const dayMap = {
                                'MONDAY': 0, 'MON': 0,
                                'TUESDAY': 1, 'TUE': 1, 'TUES': 1,
                                'WEDNESDAY': 2, 'WED': 2,
                                'THURSDAY': 3, 'THU': 3, 'THUR': 3,
                                'FRIDAY': 4, 'FRI': 4,
                              };

                              const normalizeDayKey = (raw) => {
                                if (!raw) return null;
                                const s = String(raw).trim();
                                if (!s) return null;
                                const u = s.toUpperCase();
                                if (dayMap[u] !== undefined) return u;
                                // Handle strings like "Mon" or "Monday" embedded in text
                                const m = /(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|MON|TUE|TUES|WED|THU|THUR|FRI)/i.exec(u);
                                return m ? String(m[1]).toUpperCase() : null;
                              };

                              const SLOTS_PER_DAY = 10;
                              const parseTimeToMinutes = (raw) => {
                                if (!raw) return null;
                                let s = String(raw).trim();
                                if (!s) return null;
                                // Accept 8.30 as 8:30
                                s = s.replace(/(\d)\.(\d{2})\b/g, '$1:$2');
                                const m = s.match(/^(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)?$/i);
                                if (!m) return null;
                                let hh = parseInt(m[1], 10);
                                const mm = parseInt(m[2], 10);
                                if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
                                const ampm = m[3] ? String(m[3]).toUpperCase() : null;
                                if (ampm) {
                                  if (ampm === 'PM' && hh < 12) hh += 12;
                                  if (ampm === 'AM' && hh === 12) hh = 0;
                                }
                                return hh * 60 + mm;
                              };

                              const timeToRowIdx = (timeStr) => {
                                const mins = parseTimeToMinutes(timeStr);
                                if (mins === null) return null;
                                const base = 8 * 60 + 30;
                                const idx = Math.round((mins - base) / 60);
                                if (!Number.isFinite(idx)) return null;
                                if (idx < 0 || idx >= SLOTS_PER_DAY) return null;
                                return idx;
                              };

                              const extractFirstTimeFromText = (text) => {
                                if (!text) return null;
                                const s = String(text);
                                // Grab first HH:MM (optionally followed by AM/PM)
                                const m = s.match(/\b(\d{1,2}[:.]\d{2})\s*(AM|PM)?\b/i);
                                if (!m) return null;
                                return (m[2] ? `${m[1].replace('.', ':')} ${m[2]}` : m[1].replace('.', ':'));
                              };

                              const pickRowFromTimeSlot = (slot) => {
                                const n = parseInt(slot, 10);
                                if (Number.isNaN(n)) return null;
                                // Some payloads store a global timeslot index (0..days*slots-1)
                                if (n >= SLOTS_PER_DAY) return n % SLOTS_PER_DAY;
                                return n;
                              };

                              // Prefer explicit coordinates if backend provided them
                              if (violation && typeof violation === 'object') {
                                if (violation.row !== undefined && violation.col !== undefined) {
                                  const rr = parseInt(violation.row, 10);
                                  const cc = parseInt(violation.col, 10);
                                  if (!Number.isNaN(rr) && !Number.isNaN(cc)) {
                                    targetRow = rr;
                                    targetCol = cc;
                                  }
                                }
                              }

                              const parseText = [
                                (typeof violation === 'string' ? violation : null),
                                (violation && typeof violation === 'object' ? violation.location : null),
                                itemText,
                              ].filter(Boolean).join(' ');
                              
                              // If we still don't have coordinates, derive day/time from fields OR rendered text
                              if (targetRow === null || targetCol === null) {
                                const rawDay = (violation && typeof violation === 'object' && violation.day) ? violation.day : null;
                                const dayFromTextMatch = /(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|MON|TUE|TUES|WED|THU|THUR|FRI)/i.exec(parseText);
                                const dKey = normalizeDayKey(rawDay || (dayFromTextMatch ? dayFromTextMatch[1] : null));
                                if (dKey && dayMap[dKey] !== undefined) {
                                  targetCol = dayMap[dKey] + 1; // +1 because col 0 is Time header
                                }

                                const rawTime = (violation && typeof violation === 'object' && violation.time) ? violation.time : null;
                                const timeCandidate = rawTime || extractFirstTimeFromText(parseText);

                                if (violation && typeof violation === 'object' && violation.time_slot !== undefined) {
                                  const rr = pickRowFromTimeSlot(violation.time_slot);
                                  if (rr !== null) targetRow = rr;
                                } else if (timeCandidate) {
                                  targetRow = timeToRowIdx(timeCandidate);
                                }
                              }

                              // If we have group + course, try to pinpoint the exact occurrence
                              if ((targetRow === null || targetCol === null) && violation && typeof violation === 'object') {
                                const occ = (violation.group && violation.course)
                                  ? findCourseOccurrences(violation.group, violation.course)
                                  : [];
                                if (occ.length > 0) {
                                  // If we parsed a day/time, try to match it; else just take the first.
                                  const best = (targetRow !== null && targetCol !== null)
                                    ? occ.find(o => o.row === targetRow && o.col === targetCol) || occ[0]
                                    : occ[0];
                                  targetRow = best.row;
                                  targetCol = best.col;
                                }
                              }

                              // Fallback: for violations that don't carry day/time fields (e.g. Consecutive Slot Violations),
                              // derive the first offending cell from the group's timetable.
                              if ((targetRow === null || targetCol === null) && internalName === 'Consecutive Slot Violations') {
                                const occ = (violation && violation.group && violation.course)
                                  ? findCourseOccurrences(violation.group, violation.course)
                                  : [];
                                if (occ.length > 0) {
                                  targetRow = occ[0].row;
                                  targetCol = occ[0].col;
                                }
                              }

                              onNavigate(targetGroupIdx, targetRow, targetCol);
                            //   onClose(); // Keep closed or open? User said "redirects me", usually implies closing and showing logic.
                            }}
                          >
                            {itemText}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div style={{ textAlign: 'right', marginTop: '20px', paddingTop: '15px', borderTop: '1px solid #f0f0f0' }}>
          <button
            onClick={onClose}
            style={{ backgroundColor: '#11214D', color: 'white', padding: '8px 16px', border: 'none', borderRadius: '5px', cursor: 'pointer' }}
          >
            Close
          </button>
        </div>
      </div>
    </>
  );
};

export default ConstraintModal;
