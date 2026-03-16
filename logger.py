import sys

class Logger:
    def __init__(self, filename):
        self.file = open(filename, 'a', encoding='utf-8', errors='replace')  # 追加模式
        self.stdout = sys.stdout
        self.stderr = sys.stderr
    
    def write(self, message):
        try:
            # 确保写入文件时使用UTF-8
            self.file.write(message)
            self.file.flush()
            
            # 控制台输出保持原编码（通常为GBK）
            self.stdout.write(message)
        except UnicodeEncodeError:
            # 处理编码问题，替换无法编码的字符
            safe_message = message.encode(sys.stdout.encoding, 
                                         errors='replace').decode(sys.stdout.encoding)
            self.stdout.write(safe_message)
    
    def flush(self):
        self.file.flush()
        self.stdout.flush()
