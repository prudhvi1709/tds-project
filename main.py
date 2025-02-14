# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "openai",
#     "python-multipart",
#     "requests",
#     "python-dotenv"
# ]
# ///

import os
import subprocess
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

AIPROXY_TOKEN = os.environ["AIPROXY_TOKEN"]
SYSTEM_PROMPT = """You are a DataWorks automation agent generating precise, secure code for data tasks.

SECURITY:
- Accept input/output paths only under C:\\data; error otherwise.
- No file deletions/modifications; validate paths for operations.
- Allow SELECT queries only for SQLite/DuckDB.

TASKS:
- Data processing, API fetching (save under C:\\data), Git (clone/commit under C:\\data), web scraping, image/audio processing, format conversions, CSV/JSON filtering, external script execution.

GUIDELINES:
- Code in Python (with imports, error handling) or Shell commands.
- Use Windows paths; DO NOT import unneccesary packages; If any packages are requeired to be downloaded, include in python script itself  (example: try: import PIL except Importerror, modulenotfounderror: os.system('pip install PIL')).
- LLM/API: Use https://llmfoundry.straive.com/openai/v1/chat/completions with `Bearer {os.environ['AIPROXY_TOKEN']}:llm-code` with model gpt-4o-mini; handle errors.
- For tasks with extraction of data from image, convert image to base64, pass the task and encoded image (something like : base64.b64encode(image_file.read()).decode('utf-8')) to an LLM and get the required data (use api calls for that).
- Dates: ISO 8601, dateutil.parser, handle invalid formats.

Return code only (no explanation). """

def execute_code(code):
    try:
        print(f"Executing code: {code}")

        # Check if the code looks like Python (has imports or Python-specific syntax)
        is_python = 'import' in code or 'def ' in code or 'print(' in code

        if is_python:
            # Execute Python code by writing to a temporary file and running it
            import tempfile

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name

            try:
                if os.name == 'nt':
                    process = subprocess.run(
                        ['python', temp_file],
                        shell=True,
                        text=True,
                        capture_output=True
                    )
                else:
                    process = subprocess.run(
                        ['python3', temp_file],
                        shell=True,
                        text=True,
                        capture_output=True
                    )

                os.unlink(temp_file)  # Clean up the temporary file

                print(f"Output: {process.stdout}")
                print(f"Errors: {process.stderr}")

                if process.returncode != 0:
                    raise Exception(f"Command failed with error: {process.stderr}")
                return process.stdout
            finally:
                # Ensure temp file is deleted even if an error occurs
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
        else:
            # Execute shell commands directly
            if os.name == 'nt':
                process = subprocess.run(code, shell=True, text=True, capture_output=True)
            else:
                process = subprocess.run(
                    code,
                    shell=True,
                    text=True,
                    capture_output=True,
                    executable='/bin/bash'
                )

            print(f"Output: {process.stdout}")
            print(f"Errors: {process.stderr}")

            if process.returncode != 0:
                raise Exception(f"Command failed with error: {process.stderr}")
            return process.stdout

    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Task execution failed: {str(e)}\nOutput: {e.output if hasattr(e, 'output') else ''}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error during execution: {str(e)}"
        )

def convert_path_to_windows(path):
    if path.startswith('/'):
        # Convert Unix-style path to Windows-style
        path = path.replace('/', '\\')
    return path

def generate_code_with_llm(task_description):
    # Convert paths in the task description to Windows format
    task_description = convert_path_to_windows(task_description)

    try:
        response = requests.post(
            "https://llmfoundry.straive.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {AIPROXY_TOKEN}:tds-project"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": task_description}
                ]
            },
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        if 'choices' not in result or not result['choices']:
            raise HTTPException(
                status_code=500,
                detail="Invalid response from LLM service"
            )

        code = result['choices'][0]['message']['content']
        code = code.replace('```python', '').replace('```bash', '').replace('```', '').strip()
        return code
    except requests.RequestException as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM service error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating code: {str(e)}"
        )

@app.post("/run")
async def run_task(
    request: Request,
    task: str = Query(..., description="The plain-English task description")
):
    # Input validation
    if not task or not task.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "Task description cannot be empty",
                "error_type": "INPUT_VALIDATION"
            }
        )

    try:
        code = generate_code_with_llm(task)
        result = execute_code(code)
        return {
            "status": "success",
            "output": result,
            "code": code
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions with consistent format
        if not isinstance(e.detail, dict):
            e.detail = {
                "status": "error",
                "message": str(e.detail),
                "error_type": "TASK_ERROR" if e.status_code == 400 else "SYSTEM_ERROR"
            }
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
                "error_type": "SYSTEM_ERROR"
            }
        )

@app.get("/read")
async def read_file(path: str = Query(..., description="Path to the file to read")):
    # Input validation
    if not path or not path.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "message": "File path cannot be empty",
                "error_type": "INPUT_VALIDATION"
            }
        )

    try:
        # Security check for path
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "error",
                    "message": "File not found",
                    "error_type": "NOT_FOUND"
                }
            )

        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {
                "status": "success",
                "content": content
            }
        except UnicodeDecodeError:
            # Try reading as binary for non-text files
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "message": "File appears to be binary or not UTF-8 encoded",
                    "error_type": "INVALID_FILE_TYPE"
                }
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": f"Error reading file: {str(e)}",
                "error_type": "SYSTEM_ERROR"
            }
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
