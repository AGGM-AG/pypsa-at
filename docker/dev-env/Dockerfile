# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: CC0-1.0

FROM condaforge/mambaforge

LABEL org.opencontainers.image.source https://github.com/AGGM-AG/pypsa-at

RUN conda update -n base conda
RUN conda install -n base conda-libmamba-solver
RUN conda config --set solver libmamba

RUN apt-get update && apt-get install -y bash git make

RUN conda --version

WORKDIR /pypsa-at

COPY ./envs ./temp

RUN conda env create -n pypsa-at -f temp/linux-64.lock.yaml
RUN conda init bash
RUN echo "conda activate pypsa-at" >> ~/.bashrc

SHELL ["/bin/bash", "--login", "-c"]
ENV PATH=/opt/conda/envs/pypsa-at/bin:$PATH

RUN rm -r temp
RUN conda clean -afy && \
    rm -rf /tmp/*

CMD ["bash"]
