FROM alpine:3.22

ENV TARGET=run

RUN apk update && apk add --no-cache git py3-pip

RUN git clone https://github.com/deborahgu/soundcork.git

RUN pip install --break-system-packages -r /soundcork/requirements.txt

WORKDIR /soundcork/soundcork

RUN cp .env.shared .env.private

CMD fastapi ${TARGET} main.py
