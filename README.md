The QODBC Chatbot System is an advanced AI-powered support solution that leverages cutting-edge natural language processing (NLP) and large language models (LLMs) to deliver intelligent, context-aware responses. Built on a robust architecture combining Flask for backend services, MySQL for data persistence, and Pinecone for vector search capabilities, the system utilizes the Mistral-7B LLM through OpenRouter's API to generate human-like responses. The chatbot intelligently processes user queries by first retrieving semantically relevant content from its knowledge base using state-of-the-art sentence embeddings (all-mpnet-base-v2 model), then synthesizing comprehensive answers while adapting tone based on real-time sentiment analysis.

Key features include sophisticated conversation management with session tracking, seamless human handoff capabilities, and a continuous learning loop that incorporates user feedback to improve response quality. The system's document processing pipeline automatically ingests and chunks web content using optimized NLP techniques, creating a dynamic knowledge base that evolves with your content. With configurable parameters for response generation and built-in monitoring tools, this solution represents a powerful fusion of retrieval-augmented generation (RAG) architecture and traditional chatbot functionality, delivering enterprise-grade AI support with minimal maintenance overhead.

Table of Contents
1-Overview
2-System Architecture
3-Features
4-Installation
5-Configuration
6-Database Setup
7-API Documentation
8-Workflow Diagrams

Overview
The QODBC Chatbot System is a comprehensive AI-powered support solution that combines:

- Natural language processing

- Knowledge base retrieval from Pinecone vector database

- Conversation history tracking

- User management

- Sentiment analysis
  The system provides both automated responses from an AI chatbot and the ability to escalate to human support staff when needed.


![Screenshot 2025-06-29 120456](https://github.com/user-attachments/assets/4f17b3f2-a4fa-4ab2-8cce-732e90936461)

Key Components:

1-Frontend: Web interface built with HTML/CSS/JS
2-Backend: Flask application handling routes and business logic
3-Database: MySQL for user data and conversation history
4-Vector Database: Pinecone for document embeddings and semantic search
5-LLM: OpenRouter API for generating responses


Features
1-Core Features

->Conversation Management:
->Track conversation history by session
->Store user questions and bot responses
->Contextual follow-up handling

2-User Management:

->User signup and authentication
->Session tracking with cookies
->Profile management
->Knowledge Base:

3-Web crawling and content ingestion

->Semantic search capabilities
->Document chunking and embedding

4-AI Responses:

->Sentiment analysis for tone adjustment
->Context-aware answers
->Feedback handling for response improvement

![deepseek_mermaid_20250629_f1a3cf](https://github.com/user-attachments/assets/6ad7bf4d-8738-4b2c-9499-0b3f6b27b2a1)QODBC Chatbot System - Documentation

Advanced Features

- Human Handoff: Escalate to human support staff when needed
- Multi-session Support: Users can have multiple concurrent conversations
- Response Feedback: Thumbs up/down system to improve answers

Installation
->Prerequisites
  ->Python 3.8+
  ->MySQL Server
  ->Pinecone account
  ->OpenRouter API key

![deepseek_mermaid_20250629_a4038e](https://github.com/user-attachments/assets/926bac8a-576a-40e6-aa58-5e590c49c790)





















  
