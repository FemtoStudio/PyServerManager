from .execute_manager import ExecuteThread, ExecuteThreadManager

def main():


    args = {
        'some_arg': 'value',
        'another_arg': [1, 2, 3],
    }

    python_exe = r'E:\ai_projects\ai_portal\.venv\Scripts\python.exe'  # Adjust to your Python executable path
    script_path = r'test_scripts/test_script.py'  # Adjust to your script path
    pre_cmd = 'echo Starting execution...'
    post_cmd = 'echo Execution finished.'
    export_env = {'MY_VAR': 'value'}
    custom_activation_script = '/path/to/activate.sh'  # Or .bat file for Windows

    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=script_path,
        export_env=export_env,
        custom_activation_script=custom_activation_script
    )
    thread = manager.get_thread(
        args=args,
        open_new_terminal=True
    )

    thread.start()

    # Optionally, wait for the thread to finish
    thread.join()

    # Clean up terminated threads
    manager.clean_up_threads()

if __name__ == '__main__':
    main()
