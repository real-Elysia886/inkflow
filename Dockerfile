FROM python:3.13-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir . -i https://pypi.tuna.tsinghua.edu.cn/simple

EXPOSE 8000

CMD ["python", "main.py", "--host", "0.0.0.0"]
