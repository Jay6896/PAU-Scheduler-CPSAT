import React, { useState, useEffect } from 'react';
import './TimetableResults.css';
import InteractiveTimetable from './InteractiveTimetable';

const TimetableResults = ({ result, uploadId }) => {
  const [timetablesData, setTimetablesData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (result && result.timetables) {
      // Transform the result data into the format expected by InteractiveTimetable
      const transformedData = result.timetables.map((timetable, idx) => {
        return {
          student_group: timetable.student_group || timetable.group_name || `Group ${idx + 1}`,
          timetable: timetable.timetable || timetable.rows || []
        };
      });
      
      setTimetablesData(transformedData);
      setLoading(false);
    }
  }, [result]);

  if (loading || !timetablesData) {
    return (
      <section className="results-section">
        <div className="results-header">
          <div className="results-header-left">
            <div className="results-icon">⏳</div>
            <h3 className="results-title">Loading Timetable...</h3>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="results-section">
      <InteractiveTimetable 
        timetablesData={timetablesData}
        uploadId={uploadId}
        onSave={(updatedTimetables, updatedManualCells) => {
          // Handle saving updated timetables if needed
          console.log('Timetables updated:', updatedTimetables);
          console.log('Manual cells:', updatedManualCells);
        }}
      />
    </section>
  );
};

export default TimetableResults;