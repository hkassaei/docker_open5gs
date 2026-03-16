# Extends the existing docker_ueransim image with pjsua for e2e voice testing.

FROM docker_ueransim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libssl-dev \
    libasound2-dev \
    libopus-dev \
    libopencore-amrnb-dev \
    libopencore-amrwb-dev \
    libvo-amrwbenc-dev \
    dnsutils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build PJSIP from source
WORKDIR /usr/local/src
RUN git clone --depth 1 --branch 2.14.1 https://github.com/pjsip/pjproject.git && \
    cd pjproject && \
    echo '#define PJ_HAS_SSL_SOCK 1' > pjlib/include/pj/config_site.h && \
    echo '#define PJMEDIA_HAS_OPENCORE_AMRNB_CODEC 1' >> pjlib/include/pj/config_site.h && \
    echo '#define PJMEDIA_HAS_OPENCORE_AMRWB_CODEC 1' >> pjlib/include/pj/config_site.h && \
    echo '#define PJMEDIA_HAS_OPUS_CODEC 1' >> pjlib/include/pj/config_site.h && \
    ./configure --prefix=/usr/local \
        --enable-shared \
        --with-ssl \
        --with-opencore-amr \
        --with-opus && \
    make dep && \
    make -j$(nproc) && \
    make install && \
    cp pjsip-apps/bin/pjsua-* /usr/local/bin/pjsua && \
    chmod +x /usr/local/bin/pjsua && \
    cd / && rm -rf /usr/local/src/pjproject && \
    ldconfig

WORKDIR /UERANSIM/build

COPY pjsua_entrypoint.sh /usr/local/bin/pjsua_entrypoint.sh
RUN chmod +x /usr/local/bin/pjsua_entrypoint.sh

# Keep the original UERANSIM entrypoint — the e2e init script will call it
CMD ["/ueransim_image_init.sh"]
