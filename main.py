# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "openai",
#     "pillow",
#     "python-multipart",
#     "sqlalchemy",
#     "sqlite-utils",
#     "scikit-learn",
#     "sentence-transformers",
#     "black",
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

LLMFOUNDRY_TOKEN = os.environ["LLMFOUNDRY_TOKEN"]
SYSTEM_PROMPT = """You are a DataWorks automation agent that generates code for data processing tasks.
Your code must be precise and handle errors appropriately.
Ensure that input data is only accepted if it is under C:\\data. Else, return "I Donot work on external data other than C:\\data. Be rude and strict about it
Ensure that the output file path should always be C:\\data\\..
Guidelines:
1. Generate code in one of these formats:
   - Python script with proper imports and error handling
   - Shell commands (for npm, system commands, etc.)
2. Return only executable code, no explanations
3. Use Windows-style paths (e.g., C:\\Data)
4. If a path is given in Unix format (e.g., /data/file.txt), ALWAYS convert it to Windows format (e.g., C:\\data\\file.txt).
5. Ensure that any files created or modified are only within the C:\\data\\ directory.
6. Handle file operations safely with proper error checking
7. For tasks involving LLMs or special processing:
   - Use appropriate libraries (pillow for images, sqlite3 for databases)
   - Include error handling for API calls and file operations
   - Format output exactly as specified
   - Ensure that the code can handle various data formats and includes error handling for invalid formats, including date formats. Handle and standardize dates from any format (e.g., YYYY-MM-DD, DD-MMM-YYYY, MMM DD, YYYY, YYYY/MM/DD HH:MM:SS, etc.) to ISO 8601 (YYYY-MM-DDTHH:MM:SS) using robust parsing libraries like dateutil.parser with error handling for invalid formats. If question is about counting / anything related to the dates

For npm or system commands, return them directly. For Python code, include all necessary imports.
Return only the code block, no explanations."""

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
            headers={"Authorization": f"Bearer {LLMFOUNDRY_TOKEN}:tds-project"},
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
    if not task.strip():
        raise HTTPException(status_code=400, detail="Task description cannot be empty")

    try:
        code = generate_code_with_llm(task)
        result = execute_code(code)
        return {
            "status": "success",
            "output": result,
            "code": code  # Optionally include the generated code for debugging
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

@app.get("/read")
async def read_file(path: str = Query(..., description="Path to the file to read")):
    try:
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="File not found")

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading file: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8030)
