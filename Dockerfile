FROM public.ecr.aws/lambda/python:3.12
RUN dnf install -y libstdc++ && dnf clean all
COPY requirements.txt requirements.lock ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir --only-binary=:all: -r ${LAMBDA_TASK_ROOT}/requirements.txt
COPY heapy_ocr ${LAMBDA_TASK_ROOT}/heapy_ocr
CMD ["heapy_ocr.worker.lambda_handler"]
