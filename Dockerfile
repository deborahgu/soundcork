FROM alpine3:22

ENV TARGET=run

ENV BASEURL=http://soundcork.local.example.com

ENV PORT=8000

ENV DATADIR=/home/soundcork/db

RUN apk update && apk add --no-cache git py3-pip

EXPOSE ${PORT}/tcp

RUN git clone https://github.com/deborahgu/soundcork.git

WORKDIR /soundcork

RUN pip install --break-system-packages -r requirements.txt

WORKDIR /soundcork/soundcork

RUN echo base_url = "${BASEURL}:${PORT}" > .env.private

RUN echo data_dir = "${DATADIR}" >> .env.private

ENTRYPOINT fastapi ${TARGET} main.py
