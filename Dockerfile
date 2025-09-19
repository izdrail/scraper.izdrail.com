# ---------------------------
# Base image
# ---------------------------
FROM ubuntu:latest
LABEL maintainer="Bogdanel Stefan <stefan@izdrail.com>"

# ---------------------------
# Install system dependencies
# ---------------------------
RUN apt update && apt install -y \
    curl \
    nodejs \
    npm \
    python3 \
    python3-pip \
    python3-venv \
    net-tools \
    software-properties-common \
    openjdk-17-jdk \
    maven \
    git \
    wget \
    && apt-get clean

# ---------------------------
# Setup Python Virtual Environment
# ---------------------------
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install supervisor pipx

# Use venv as default
ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------
# Working directory
# ---------------------------
WORKDIR /home/scraper

# ---------------------------
# Clone Skraper source
# ---------------------------
RUN git clone https://github.com/laravelcompany/skraper.git .

# ---------------------------
# Build CLI + VAST API
# ---------------------------
RUN ./mvnw clean package -DskipTests=true



# ---------------------------
# Move built jar to usable path
# ---------------------------
RUN mkdir -p /usr/local/skraper \
    && cp /home/scraper/cli/target/cli.jar /usr/local/skraper/skraper.jar

RUN chmod +x /usr/local/skraper/skraper.jar

# ---------------------------
# Fancy Zsh shell (optional)
# ---------------------------
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.1.5/zsh-in-docker.sh)" -- \
    -t https://github.com/denysdovhan/spaceship-prompt \
    -a 'SPACESHIP_PROMPT_ADD_NEWLINE="false"' \
    -a 'SPACESHIP_PROMPT_SEPARATE_LINE="false"' \
    -p git \
    -p ssh-agent \
    -p https://github.com/zsh-users/zsh-autosuggestions \
    -p https://github.com/zsh-users/zsh-completions

# ---------------------------
# Install Python requirements
# ---------------------------
COPY ./requirements.txt /home/scraper/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /home/skraper/requirements.txt \
    && pip install text2emotion pymupdf4llm sqlalchemy yake fastapi_versioning tls_client uvicorn gnews \
    && python3 -m nltk.downloader -d /usr/local/share/nltk_data wordnet punkt stopwords vader_lexicon \
    && python3 -m spacy download en_core_web_md \
    && python3 -m textblob.download_corpora

# ---------------------------
# Expose default VAST API port
# ---------------------------
EXPOSE 3366

# Supervisord configuration
COPY docker/supervisord.conf /etc/supervisord.conf

# Copy application

COPY . .

# Run application
ENTRYPOINT ["supervisord", "-c", "/etc/supervisord.conf", "-n"]