import React from 'react'
import './Footer.css'

const currentYear = new Date().getFullYear();

function Footer() {
  return (
    <footer className="app-footer">
      <div className="footer-content">
        <p>&copy; {currentYear} PAU Timetable Scheduler. All Rights Reserved.</p>
      </div>
    </footer>

  )
}

export default Footer