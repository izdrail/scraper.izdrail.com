# Base image
FROM ubuntu:latest
#FROM ubuntu:latest
LABEL maintainer="Bogdanel Stefan  <stefan@izdrail.com>"

# Install dependencies
RUN apt update && apt install -y \
    curl \
    nodejs \
    npm \
    python3 \
    python3-pip \
    net-tools \
    software-properties-common \
    openjdk-17-jdk \
    maven \
    && apt-get clean

# Install pip packages and supervisord
RUN pip install --no-cache-dir --upgrade pip \
    && pip install supervisor pipx

LABEL maintainer="Bogdanel Stefan <stefan@izdrail.com>"

# 📁 Working dir
WORKDIR /home/skraper

# 📦 System dependencies
RUN apt-get update && apt-get install -y \
    git \
    maven \
    && apt-get clean

# ⬇️ Clone Skraper
RUN git clone https://github.com/laravelcompany/skraper.git .

# 🛠️ Build CLI + VAST API
RUN ./mvnw clean package -DskipTests=true

# 📁 Move built jar to a usable path
RUN mkdir -p /usr/local/skraper \
    && cp /home/skraper/cli/target/cli.jar /usr/local/skraper/skraper.jar


# Customize shell with Zsh
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.1.5/zsh-in-docker.sh)" -- \
    -t https://github.com/denysdovhan/spaceship-prompt \
    -a 'SPACESHIP_PROMPT_ADD_NEWLINE="false"' \
    -a 'SPACESHIP_PROMPT_SEPARATE_LINE="false"' \
    -p git \
    -p ssh-agent \
    -p https://github.com/zsh-users/zsh-autosuggestions \
    -p https://github.com/zsh-users/zsh-completions

# Copy Requirements
COPY ./requirements.txt /home/skraper/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /home/osint/requirements.txt \
    && pip install text2emotion pymupdf4llm sqlalchemy yake fastapi_versioning tls_client uvicorn gnews \
    && python3 -m nltk.downloader -d /usr/local/share/nltk_data wordnet punkt stopwords vader_lexicon \
    && python3 -m spacy download en_core_web_md \
    && python3 -m textblob.download_corpora



# 🌐 Expose default VAST API port
EXPOSE 3366

