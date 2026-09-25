import os

file_path = '/home/btl/lakshmi/asset_app/models.py'
with open(file_path, 'r') as f:
    content = f.read()

target = "    storage = models.CharField(max_length=50, blank=True, null=True)"
replacement = "    storage = models.CharField(max_length=50, blank=True, null=True)\n    processor = models.CharField(max_length=100, blank=True, null=True)\n    graphic_card = models.CharField(max_length=100, blank=True, null=True)"
content = content.replace(target, replacement)

with open(file_path, 'w') as f:
    f.write(content)
