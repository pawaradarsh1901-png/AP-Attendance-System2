import zipfile
import os

def create_deploy_zip():
    zip_name = 'attendance_deploy.zip'
    # Files to include
    include_files = [
        'app.py',
        'wsgi.py',
        'requirements.txt',
        'Procfile',
        'attendance.db'
    ]
    # Directories to include
    include_dirs = [
        'templates'
    ]

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add files
        for file in include_files:
            if os.path.exists(file):
                zipf.write(file)
                print(f"Added: {file}")
        
        # Add directories
        for directory in include_dirs:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path)
                    print(f"Added: {file_path}")

    print(f"\nSuccessfully created {zip_name}!")
    print("You can now upload this zip to PythonAnywhere or any other server.")

if __name__ == "__main__":
    create_deploy_zip()
