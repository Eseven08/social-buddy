# social-buddy container -- run the buddy 24/7 on any always-on host.
#
# The QQ protocol bridge (NapCatQQ etc.) usually runs on the host next to a
# QQ client; point SOCIAL_BUDDY_ONE_BOT_HTTP at it (host.docker.internal on
# Docker Desktop for Windows/Mac).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# persist memory outside the container
VOLUME /data
ENV SOCIAL_BUDDY_STORE_DIR=/data

EXPOSE 8765

CMD ["python", "main.py", "onebot"]
