import React, { useState } from 'react';
import './DownloadModal.css';

// Base URL helper
const getApiBaseUrl = () => {
    if (process.env.NODE_ENV === 'development') return '';
    if (process.env.REACT_APP_API_BASE_URL) return process.env.REACT_APP_API_BASE_URL;
    return 'https://pau-001-pau-timetable-scheduler.hf.space';
};

const DownloadModal = ({ isOpen, onClose, timetables, uploadId }) => {
  const [downloading, setDownloading] = useState(false);

  if (!isOpen) return null;

  const downloadFromBackend = async (format) => {
    if (!uploadId) {
      alert(`Upload ID missing (${uploadId}). Cannot download from backend.`);
      return;
    }

    setDownloading(true);
    const baseUrl = getApiBaseUrl();
    const url = `${baseUrl}/api/export/${format}/${uploadId}`;

    try {
      const res = await fetch(url, { method: 'GET' });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Export failed (${res.status})`);
      }

      const blob = await res.blob();

      // Try to honor backend filename
      let filename = null;
      const disposition = res.headers.get('content-disposition') || res.headers.get('Content-Disposition');
      if (disposition) {
        const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition);
        filename = decodeURIComponent(match?.[1] || match?.[2] || '');
      }
      if (!filename) {
        const prefixMap = {
          sst: 'SST_Timetables',
          tyd: 'TYD_Timetables',
          lecturer: 'Lecturer_Timetables',
          classrooms: 'Classrooms_Scheduled',
        };
        const prefix = prefixMap[format] || 'Export';
        filename = `${prefix}_${uploadId}.xlsx`;
      }

      const objectUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (e) {
      console.error('Download failed:', e);
      alert(`Download failed: ${e?.message || e}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <div className="modal-overlay" onClick={onClose}></div>
      <div className="download-modal">
        <div className="modal-header">
          <h3 className="modal-title" style={{ fontSize: '18px', fontWeight: '600', color: '#11214D', margin: 0 }}>Download Timetables</h3>
          <button className="modal-close" onClick={onClose} style={{background: 'none', border: 'none', fontSize: '24px', color: '#666', cursor: 'pointer'}}>×</button>
        </div>

        <div className="download-options">
          {/* SST Timetables */}
          <div className="download-option">
            <span style={{ flex: 1, fontSize: '16px', fontWeight: '500' }}>
              Download SST Timetables
            </span>
            <button
              onClick={() => downloadFromBackend('sst')}
              disabled={downloading}
              style={{
                backgroundColor: '#11214D',
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '5px',
                cursor: downloading ? 'wait' : 'pointer',
                fontSize: '14px'
              }}
            >
              Download
            </button>
          </div>

          {/* TYD Timetables */}
          <div className="download-option">
            <span style={{ flex: 1, fontSize: '16px', fontWeight: '500' }}>
              Download TYD Timetables
            </span>
            <button
              onClick={() => downloadFromBackend('tyd')}
              disabled={downloading}
              style={{
                backgroundColor: '#11214D',
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '5px',
                cursor: downloading ? 'wait' : 'pointer',
                fontSize: '14px'
              }}
            >
              Download
            </button>
          </div>

          {/* Lecturer Timetables */}
           <div className="download-option">
            <span style={{ flex: 1, fontSize: '16px', fontWeight: '500' }}>
              Download all Lecturer Timetables
            </span>
            <button
              onClick={() => downloadFromBackend('lecturer')}
              disabled={downloading}
              style={{
                backgroundColor: '#11214D',
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '5px',
                cursor: downloading ? 'wait' : 'pointer',
                fontSize: '14px'
              }}
            >
              Download
            </button>
          </div>

          {/* Classrooms Scheduled */}
          <div className="download-option">
            <span style={{ flex: 1, fontSize: '16px', fontWeight: '500' }}>
              Download Classrooms Scheduled
            </span>
            <button
              onClick={() => downloadFromBackend('classrooms')}
              disabled={downloading}
              style={{
                backgroundColor: '#11214D',
                color: 'white',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '5px',
                cursor: downloading ? 'wait' : 'pointer',
                fontSize: '14px'
              }}
            >
              Download
            </button>
          </div>
        </div>
        
        <div style={{ textAlign: "right", marginTop: "20px", paddingTop: "15px", borderTop: "1px solid #f0f0f0" }}>
           <button onClick={onClose} style={{ backgroundColor: "#6c757d", color: "white", padding: "8px 16px", border: "none", borderRadius: "5px", cursor: "pointer" }}>Close</button>
        </div>
      </div>
    </>
  );
};

export default DownloadModal;
