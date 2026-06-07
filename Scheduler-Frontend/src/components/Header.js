import React from 'react';
import './Header.css';
import Logo from '../assets/logo.png';

const Header = ({ onShowInstructions }) => {
  return (
    <header className="header">
      <nav className="nav-container">
        <div className="logo-section">
          <img className="logo" src={Logo} alt='Logo'/>
          {/* <div className="university-name">Timetable Generator</div> */}
        </div>

        <div className="university-name">Timetable Scheduler</div>
        
        <div className="nav-right">
          <button 
            className="instructions-btn" 
            onClick={onShowInstructions}
            type="button"
          >
            How to Use
          </button>
        </div>
      </nav>
    </header>
  );
};

export default Header;