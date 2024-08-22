import os
import json
from loguru import logger

from magic_pdf.pipe.UNIPipe import UNIPipe
from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter

import magic_pdf.model as model_config
model_config.__use_inside_model__ = True



def remove_extension(filename):
    # 使用 os.path.splitext() 分离文件名和扩展名
    base_name, extension = os.path.splitext(filename)
    return base_name
def processPdf2MD(item):
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    dest_dir = item[2]
    filename = os.path.basename(item[1])
    demo_name = remove_extension(filename)
    pdf_path = item[1]
    model_path = os.path.join(current_script_dir, f"magic-pdf.json")
    pdf_bytes = open(pdf_path, "rb").read()
    model_json = json.loads(open(model_path, "r", encoding="utf-8").read())
    # model_json = []  # model_json传空list使用内置模型解析
    jso_useful_key = {"_pdf_type": "", "model_list": model_json}
    local_image_dir = os.path.join(dest_dir, 'images')
    image_dir = str(os.path.basename(local_image_dir))
    image_writer = DiskReaderWriter(local_image_dir)
    pipe = UNIPipe(pdf_bytes, jso_useful_key, image_writer)
    pipe.pipe_classify()
    pipe.pipe_analyze()
    pipe.pipe_parse()
    md_content = pipe.pipe_mk_markdown(image_dir, drop_mode="none")
    output_md_path = os.path.join(dest_dir, f"{demo_name}.md")
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)



