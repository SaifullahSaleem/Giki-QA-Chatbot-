from scrapy.crawler import CrawlerProcess
from giki_spider import GikiSpider

def run_spider():
    process = CrawlerProcess(settings={
        "FEEDS": {"giki_data.json": {"format": "json"}},
        "LOG_LEVEL": "ERROR",
    })
    process.crawl(GikiSpider)
    process.start()

if __name__ == "__main__":
    run_spider()
