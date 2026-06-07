import os
import sys
import webbrowser
from threading import Timer

# Add the current directory to sys.path to ensure imports work correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from Dash_UI import create_app
except ImportError as e:
    print(f"Error importing Dash_UI: {e}")
    print("Please ensure you are in the correct directory and all dependencies are installed.")
    sys.exit(1)

def open_browser(port):
    """Open the browser to the Dash app URL"""
    webbrowser.open_new(f"http://127.0.0.1:{port}/")

def main():
    """Launch the standalone Dash interface"""
    print("="*50)
    print("🎓 Launching Standalone Dash Timetable Viewer")
    print("="*50)
    print("This viewer displays the results from the latest optimization run.")
    
    # Check if data file exists to give helpful feedback
    data_path = os.path.join(current_dir, 'data', 'fresh_timetable_data.json')
    if os.path.exists(data_path):
        print(f"✅ Found data file: {data_path}")
    else:
        print(f"⚠️  Warning: Data file not found at {data_path}")
        print("   The viewer may be empty until you run differential_evolution.py")

    try:
        # Create the Dash application
        # We pass None as context since we are running standalone
        app = create_app()
        
        # Set the port for the standalone viewer
        # Using 8050 which is standard for Dash, avoiding 7860/5000 used by Flask
        port = 8050
        
        # Open browser automatically after a short delay
        Timer(1.5, open_browser, [port]).start()
        
        print(f"\n🚀 Server starting on http://127.0.0.1:{port}/")
        print("Press Ctrl+C to stop the server.")
        
        # Run the server
        # debug=True enables hot-reloading which is useful
        app.run(debug=False, port=port, use_reloader=False)
        
    except Exception as e:
        print(f"\n❌ Error launching Dash UI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()