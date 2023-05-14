import datetime
import logging
import time

from logging.handlers import TimedRotatingFileHandler

WHEN = 'MIDNIGHT'


class Logger(object):
    def __init__(self, log_file_name, log_level, logger_name, when=WHEN):

        # 创建一个logger
        self.__logger = logging.getLogger(logger_name)

        # 指定日志的最低输出级别，默认为WARN级别
        self.__logger.setLevel(log_level)

        # 创建一个handler用于写入日志文件
        # file_handler = logging.FileHandler(log_file_name)
        file_handler = TimeLoggerRolloverHandler(f"{log_file_name}_{datetime.datetime.now().strftime('%Y%m%d')}.log", when)

        # file_handler = logging.handlers.TimedRotatingFileHandler(
        #     log_file_name, when='S', interval=1, backupCount=0, encoding=None, delay=False, utc=False, atTime=None
        # )

        # 创建一个handler用于输出控制台
        # console_handler = logging.StreamHandler()

        # 定义handler的输出格式
        formatter = logging.Formatter(
            '[%(asctime)s.%(msecs)03d] - [line:%(lineno)d] - %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        # console_handler.setFormatter(formatter)

        # 给logger添加handler
        self.__logger.addHandler(file_handler)
        # self.__logger.addHandler(console_handler)

    def get_log(self):
        return self.__logger


class NsFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.time_ns()  # get current time with nanosecond precision
            s = time.strftime("%Y-%m-%d %H:%M:%S", ct)
            ms = int(round(t * 0.000001)) % 1000  # convert nanoseconds to milliseconds
            us = int(round(t * 0.001)) % 1000  # convert nanoseconds to microseconds
            # ns = t % 1000  # nanoseconds
            s = f"{s},{ms:03d}.{us:03d}"
        return s


# https://blog.csdn.net/ouxian1998/article/details/120334001
class TimeLoggerRolloverHandler(TimedRotatingFileHandler):
    def __init__(self, filename, when, interval=1, backup_count=0, encoding=None, delay=False, utc=False):
        super(TimeLoggerRolloverHandler, self).__init__(filename, when, interval, backup_count, encoding, delay, utc)

    def doRollover(self):
        """
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        current_time = int(time.time())
        dst_now = time.localtime(current_time)[-1]

        list_string = self.baseFilename.split("/")[-1].split("_")
        base_name = '_'.join(list_string[0:len(list_string)-1])
        dfn = f"{base_name}_{datetime.datetime.now().strftime('%Y%m%d')}.log"
        self.baseFilename = dfn

        if not self.delay:
            self.stream = self._open()
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at = new_rollover_at + self.interval
        if (self.when == 'MIDNIGHT' or self.when.startswith('W')) and not self.utc:
            dst_at_rollover = time.localtime(new_rollover_at)[-1]
            if dst_now != dst_at_rollover:
                if not dst_now:
                    addend = -3600
                else:
                    addend = 3600
                new_rollover_at += addend
        self.rolloverAt = new_rollover_at


if __name__ == '__main__':
    log_info = Logger(log_file_name='test', log_level=logging.INFO, logger_name='info').get_log()

    while 1:
        log_info.error('test error')
        time.sleep(1)
        log_info.info('test info')
