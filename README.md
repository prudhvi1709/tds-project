# TDS Project

## Overview
The TDS Project is a FastAPI application designed to automate data tasks using a language model. It provides endpoints to run code and read files securely, ensuring that operations are performed within specified constraints.

## Features
- **Run Code**: Execute Python code or shell commands securely.
- **Read Files**: Read text files while ensuring security checks on file paths.
- **Integration with LLM**: Generate code based on plain-English task descriptions using a language model.

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/prudhvi1709/tds-project/
   cd tds-project
   ```

3. Set up environment variables:
   - Create a `.env` file in the root directory and add your `AIPROXY_TOKEN`.

## Usage
To run the application, execute the following command:
```bash
uv run main.py
```

The application will start on `http://127.0.0.1:8000`.

### API Endpoints
- **POST /run**: Execute a task based on a plain-English description.
- **GET /read**: Read the content of a specified file.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

