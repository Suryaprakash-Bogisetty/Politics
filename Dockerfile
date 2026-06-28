FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the multilingual sentiment model into the image so startup is instant
RUN python3 -c "\
from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
AutoTokenizer.from_pretrained('cardiffnlp/twitter-xlm-roberta-base-sentiment'); \
AutoModelForSequenceClassification.from_pretrained('cardiffnlp/twitter-xlm-roberta-base-sentiment'); \
print('Model cached.')"

# Copy backend source
COPY backend/ ./backend/

# Copy UI assets (served as static files by FastAPI)
COPY ui/ ./ui/

# Set working directory to backend so relative imports work
WORKDIR /app/backend

EXPOSE 5000

ENV HF_HUB_DISABLE_IMPLICIT_TOKEN=1
ENV TRANSFORMERS_VERBOSITY=error

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5000"]
