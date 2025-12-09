# giki_spider.py
import scrapy
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class GikiSpider(scrapy.Spider):
    name = "giki_spider"
    # include the pages discovered above
    start_urls = [
        "https://giki.edu.pk/fcse/faculty-profiles/",
        "https://giki.edu.pk/rd/",
        "https://giki.edu.pk/fes-labs-and-facilities/",
        "https://giki.edu.pk/mgs/research-projects-and-grants/",
        "https://giki.edu.pk/news/",
        "https://giki.edu.pk/faculty/",
        "https://giki.edu.pk/fme/",
        "https://giki.edu.pk/fbs/es-faculty-profile/",
        "https://giki.edu.pk/fmce/dche/dche-faculty-profile/",
        "https://giki.edu.pk/dce/dce-faculty-profile/",
        "https://giki.edu.pk/rd/rd-fme/",
        "https://giki.edu.pk/oric/",
    ]

    custom_settings = {
        # obey robots? set False for development only if you know what you're doing
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 0.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "USER_AGENT": "giki-scraper/1.0 (+https://giki.edu.pk)",
        # If you want to follow links discovered on the pages, enable depth limit appropriately
    }

    def parse(self, response):
        """Entry parse: detect page type and dispatch to specialized parser."""
        self.logger.info("Parsing %s", response.url)
        soup = BeautifulSoup(response.text, "html.parser")

        # Heuristics to pick parser
        if "faculty-profile" in response.url or "faculty-profiles" in response.url or "/faculty/" in response.url:
            yield from self.parse_faculty_list(response, soup)
        elif "research-projects-and-grants" in response.url or "/projects" in response.url or "/mgs/" in response.url:
            yield from self.parse_research_projects(response, soup)
        elif "/news" in response.url:
            yield from self.parse_news_listing(response, soup)
        elif "labs-and-facilities" in response.url or "/rd/" in response.url or "/rd-" in response.url:
            yield from self.parse_labs_and_research(response, soup)
        else:
            # fallback: extract page text and follow internal links up to a limit
            yield from self.parse_generic(response, soup)

        # Discover and follow internal links on the page to find deeper pages (faculty detail pages, project pages, news articles)
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            abs_url = urljoin(response.url, href)
            # only follow same-domain links
            if abs_url.startswith("https://giki.edu.pk"):
                # avoid infinite loops: skip obvious resource links
                if any(x in abs_url for x in [".pdf", ".jpg", ".png", ".zip", "#", "mailto:"]):
                    continue
                yield scrapy.Request(abs_url, callback=self.parse)

    # ---------- specialized parsers ----------
    def parse_faculty_list(self, response, soup):
        """
        Parse listing pages that contain multiple faculty entries.
        Yields faculty_profile items. Also tries to follow detail pages.
        """
        # try common selectors (these might need tuning to the actual site HTML)
        candidates = soup.select(".faculty-profile, .faculty-item, .staff-member, .profile")
        if not candidates:
            # fallback: search for blocks with <h3> or <h2> that look like names
            candidates = soup.select("article, .post, .entry, li")
        for block in candidates:
            name = self.safe_text(block.select_one(".name, h3, h2, .title"))
            research = self.safe_text(block.select_one(".research-areas, .research, .meta"))
            email = self.safe_text(block.select_one("a[href^='mailto:']"))
            profile_link = block.select_one("a[href]")
            profile_url = urljoin(response.url, profile_link.get("href")) if profile_link else response.url
            yield {
                "type": "faculty_profile",
                "name": name,
                "research": research,
                "email": email,
                "url": profile_url,
                "source": response.url,
            }

    def parse_research_projects(self, response, soup):
        """
        Parse project listing pages such as research-projects-and-grants
        """
        projects = soup.select(".project-info, .project, .research-project, .grant-item")
        if not projects:
            # find blocks with headings that look like project titles
            projects = soup.select("article, .post, li")
        for proj in projects:
            title = self.safe_text(proj.select_one(".project-title, h3, h2, .title"))
            summary = self.safe_text(proj.select_one(".project-summary, .excerpt, p"))
            link = proj.select_one("a[href]")
            url = urljoin(response.url, link.get("href")) if link else response.url
            yield {
                "type": "research_project",
                "title": title,
                "summary": summary,
                "url": url,
                "source": response.url,
            }

    def parse_news_listing(self, response, soup):
        """
        Parse news listing pages and news article pages.
        """
        posts = soup.select(".news-item, .post, .events-listing, .blog-post")
        if not posts:
            posts = soup.select("article, li")
        for post in posts:
            title = self.safe_text(post.select_one("h2, h3, .title, .entry-title, .post-title"))
            date = self.safe_text(post.select_one(".date, .posted-on, time"))
            excerpt = self.safe_text(post.select_one(".excerpt, .summary, p"))
            link = post.select_one("a[href]")
            url = urljoin(response.url, link.get("href")) if link else response.url
            yield {
                "type": "news_item",
                "title": title,
                "date": date,
                "excerpt": excerpt,
                "url": url,
                "source": response.url,
            }

    def parse_labs_and_research(self, response, soup):
        """Parse pages that list labs, research groups, or facilities."""
        groups = soup.select(".lab, .research-group, .facility, .group, .listing")
        if not groups:
            groups = soup.select("article, li")
        for g in groups:
            name = self.safe_text(g.select_one("h3, h2, .title"))
            desc = self.safe_text(g.select_one("p, .description, .excerpt"))
            link = g.select_one("a[href]")
            url = urljoin(response.url, link.get("href")) if link else response.url
            yield {
                "type": "lab_or_group",
                "name": name,
                "description": desc,
                "url": url,
                "source": response.url,
            }

    def parse_generic(self, response, soup):
        """Fallback: return page text & metadata."""
        text = soup.get_text(separator=" ", strip=True)
        title = self.safe_text(soup.select_one("title, h1"))
        yield {
            "type": "generic_content",
            "title": title,
            "content": text[:5000],  # cap length (adjust as needed)
            "url": response.url,
            "source": response.url,
        }

    # ---------- helpers ----------
    def safe_text(self, el):
        """Return stripped text for the element or empty string."""
        if not el:
            return ""
        try:
            return el.get_text(separator=" ", strip=True)
        except Exception:
            return el.text.strip() if hasattr(el, "text") else ""

