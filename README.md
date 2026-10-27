# 🤖 Smart AI Chatbot

An AI-powered chatbot built with **Python, Flask, and the Groq API**, featuring a modern chat interface designed for smooth and interactive conversations.

The goal of this project is to build a practical AI application while learning about API integration, backend development, and modern web interfaces.

## ✨ Features

- 💬 AI-powered conversations using the Groq API
- 🎨 Modern, ChatGPT-style user interface
- 🗂️ Conversation management
- ⚡ Real-time chat requests
- 📝 Markdown rendering for readable responses
- 💻 Responsive web interface
- 🔐 Environment-based API key configuration
- 🐍 Python and Flask backend

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend development |
| Flask | Web application framework |
| Groq API | AI model integration |
| HTML & CSS | User interface and styling |
| JavaScript | Chat interactions |
| Git & GitHub | Version control |

## 📁 Project Structure

```text
Smart-AI-Chatbot/
├── app/
│   ├── services/
│   ├── static/
│   └── templates/
├── docs/
├── instance/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── config.py
├── requirements.txt
├── run.py
└── README.md
```

*Note: The exact contents of the `app` folder may vary depending on your implementation.*

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/aseemraheem/Smart-AI-Chatbot.git
cd Smart-AI-Chatbot
```

### 2. Create a virtual environment

On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can use Command Prompt and run:

```bat
.venv\Scripts\activate.bat
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure your Groq API credentials:

```env
OPENAI_API_KEY=your_groq_api_key
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=openai/gpt-oss-20b
```

Replace `your_groq_api_key` with your own API key. Make sure the model ID is available to your account.

**Security:** Never upload your `.env` file or share your API key publicly.

### 5. Run the application

```bash
python run.py
```

Open the local URL shown in your terminal, usually:

```text
http://127.0.0.1:5000
```

## 🔑 API Configuration

This project uses the Groq API through an OpenAI-compatible interface. You need a Groq API key to generate AI responses.

Get your API key from [GroqCloud Console](https://console.groq.com/).

Free-tier usage is subject to the provider's current limits and availability.

## 📸 Screenshots

Add screenshots of your chatbot interface here after uploading them to the repository.

For example:

```markdown
![Chatbot Interface](docs/screenshots/chatbot.png)
```

## 🎯 Learning Goals

This project helps me develop practical experience with:

- Python application development
- REST API integration
- Flask backend development
- Frontend and backend communication
- Environment variables and API key security
- Git and GitHub workflows

## 🔮 Future Improvements

- Streaming AI responses
- Chat history persistence
- Conversation search
- Customizable chatbot settings
- Improved error handling
- Additional AI model providers

## 👨‍💻 Author

**Aseem Raheem**

Computer Science Student | Python & Web Development | AI Enthusiast

- GitHub: [@aseemraheem](https://github.com/aseemraheem)
- Portfolio: [aseemraheem.github.io](https://aseemraheem.github.io)

## 📄 License

This project is available for learning and educational purposes. A license can be added to clarify reuse and distribution permissions.
