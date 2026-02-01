FROM python:3.13-alpine

WORKDIR /app

# install dependencies
RUN apk update && apk add g++
COPY requirements.txt requirements.txt
RUN python -m pip install -r requirements.txt

# add code
COPY . .

# start dicordless
ENTRYPOINT ["python","web_exporter.py", "--traffic_archive=/data/traffic_archive", "--out_dir=/data/web_exports"]