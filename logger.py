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
    
    def isatty(self):
        """uvicorn 等库会调用 sys.stdout.isatty() 判断是否支持颜色输出"""
        return False
    
    def fileno(self):
        """返回文件描述符，供底层库使用"""
        return self.file.fileno()
    
    def close(self):
        """关闭日志文件"""
        self.file.close()
        sys.stdout = self.stdout
        sys.stderr = self.stderr
