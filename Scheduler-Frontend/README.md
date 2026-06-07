# Timetable Generator - Pan-Atlantic University

A React-based web application for generating academic timetables from Excel files. This application provides an intuitive interface for uploading course data and generating conflict-free timetables.

## Features

- 📁 **File Upload**: Drag-and-drop or browse to upload Excel files (.xlsx, .xls)
- ⚡ **Real-time Processing**: Live progress tracking during timetable generation
- 📊 **Multiple Formats**: Download timetables in Excel, PDF, or Image formats
- 🔄 **Carousel Navigation**: Browse through generated timetables for different departments/levels
- 📱 **Responsive Design**: Works seamlessly on desktop and mobile devices
- ✅ **File Validation**: Automatic validation of file types and sizes
- 🎯 **User-friendly Interface**: Clean, professional design with clear navigation

## Prerequisites

- Node.js (version 14 or higher)
- npm or yarn package manager
- Backend API server for timetable processing

## Installation

1. **Clone the repository**
   ```bash
   git clone [repository-url]
   cd timetable-generator
   ```

2. **Install dependencies**
   ```bash
   npm install
   # or
   yarn install
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   ```
   
   Edit the `.env` file with your configuration:
   ```env
   REACT_APP_API_BASE_URL=http://localhost:8000/api
   REACT_APP_UPLOAD_ENDPOINT=/timetable/upload
   REACT_APP_GENERATE_ENDPOINT=/timetable/generate
   REACT_APP_DOWNLOAD_ENDPOINT=/timetable/download
   REACT_APP_MAX_FILE_SIZE=10485760
   REACT_APP_ALLOWED_FILE_TYPES=.xlsx,.xls
   ```

## Usage

### Development

```bash
npm start
# or
yarn start
```

This runs the app in development mode. Open [http://localhost:3000](http://localhost:3000) to view it in the browser.

### Production Build

```bash
npm run build
# or
yarn build
```

Builds the app for production to the `build` folder.

### Testing

```bash
npm test
# or
yarn test
```

Launches the test runner in interactive watch mode.

## API Integration

The application expects a backend API with the following endpoints:

### Upload Endpoint
- **POST** `/api/timetable/upload`
- **Content-Type**: `multipart/form-data`
- **Body**: FormData with file
- **Response**: `{ fileId: string, filename: string, status: string }`

### Generate Endpoint
- **POST** `/api/timetable/generate`
- **Content-Type**: `application/json`
- **Body**: 
  ```json
  {
    "fileId": "string",
    "options": {
      "conflictResolution": "auto",
      "timeSlots": {
        "start": "08:00",
        "end": "17:00",
        "duration": 60
      },
      "breaks": {
        "lunch": { "start": "12:00", "duration": 60 },
        "short": { "duration": 15, "frequency": 2 }
      }
    }
  }
  ```
- **Response**: `{ timetables: Array, status: string }`

### Download Endpoint
- **POST** `/api/timetable/download`
- **Content-Type**: `application/json`
- **Body**: 
  ```json
  {
    "timetables": "Array",
    "format": "excel|pdf|image",
    "options": {
      "includeHeaders": true,
      "orientation": "landscape|portrait",
      "quality": "high"
    }
  }
  ```
- **Response**: Binary file data

## File Format Requirements

The Excel file should contain the following columns:

- **Course Code**: Unique identifier for each course (e.g., CSC101)
- **Course Title**: Full name of the course
- **Lecturer**: Instructor assigned to the course
- **Duration**: Length of each class session (in minutes)
- **Level**: Academic year (100, 200, 300, 400)
- **Department**: Academic department
- **Room Preferences**: Preferred classroom types or specific rooms
- **Time Preferences** (optional): Preferred time slots
- **Days** (optional): Preferred days of the week

### Example Excel Structure:
| Course Code | Course Title | Lecturer | Duration | Level | Department | Room Preferences |
|-------------|--------------|----------|----------|-------|------------|------------------|
| CSC101 | Intro to Computing | Dr. Smith | 60 | 100 | Computer Science | Lab |
| MAT101 | Mathematics I | Prof. Johnson | 60 | 100 | Mathematics | Classroom |

## Project Structure

```
src/
├── components/
│   ├── __tests__/
│   │   ├── FileUpload.test.js
│   │   └── TimetableGenerator.test.js
│   ├── FileUpload.js
│   ├── FileUpload.css
│   ├── Header.js
│   ├── Header.css
│   ├── InstructionsModal.js
│   ├── InstructionsModal.css
│   ├── TimetableGenerator.js
│   ├── TimetableGenerator.css
│   ├── TimetableResults.js
│   └── TimetableResults.css
├── services/
│   ├── __tests__/
│   │   └── api.test.js
│   └── api.js
├── App.js
├── App.css
├── App.test.js
├── index.js
├── index.css
└── setupTests.js
```

## Components

### TimetableGenerator
Main container component that manages the application state and coordinates between child components.

### Header
Navigation header with university branding, instructions button, and download functionality.

### FileUpload
Handles file selection, validation, drag-and-drop, and displays upload progress.

### TimetableResults
Displays generated timetables in a carousel format with navigation controls.

### InstructionsModal
Modal dialog with step-by-step usage instructions.

## Services

### API Service
Handles all API communications including file upload, timetable generation, and downloads with proper error handling and progress tracking.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REACT_APP_API_BASE_URL` | Base URL for API endpoints | `http://localhost:8000/api` |
| `REACT_APP_UPLOAD_ENDPOINT` | File upload endpoint | `/timetable/upload` |
| `REACT_APP_GENERATE_ENDPOINT` | Timetable generation endpoint | `/timetable/generate` |
| `REACT_APP_DOWNLOAD_ENDPOINT` | Download endpoint | `/timetable/download` |
| `REACT_APP_MAX_FILE_SIZE` | Maximum file size in bytes | `10485760` (10MB) |
| `REACT_APP_ALLOWED_FILE_TYPES` | Allowed file extensions | `.xlsx,.xls` |

## Testing

The project includes comprehensive tests for:

- Component rendering and user interactions
- API service functionality
- File validation and error handling
- State management and data flow

### Running Tests

```bash
# Run all tests
npm test

# Run tests with coverage
npm test -- --coverage

# Run specific test file
npm test FileUpload.test.js
```

## Styling

The application uses custom CSS with:
- Desktop system UI-inspired design
- Responsive breakpoints for mobile devices
- Consistent color scheme and typography
- Smooth animations and transitions
- Accessibility considerations

## Browser Support

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Troubleshooting

### Common Issues

1. **File Upload Fails**
   - Check file size (must be < 10MB)
   - Verify file format (.xlsx or .xls)
   - Ensure API server is running

2. **API Connection Issues**
   - Verify `REACT_APP_API_BASE_URL` in `.env`
   - Check backend server status
   - Review browser network console for errors

3. **Build Issues**
   - Clear node_modules and reinstall: `rm -rf node_modules && npm install`
   - Check Node.js version compatibility

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support and questions:
- Create an issue on GitHub
- Contact the development team
- Check the documentation wiki

---

Built with ❤️ for Pan-Atlantic University