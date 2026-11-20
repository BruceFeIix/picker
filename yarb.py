#!/usr/bin/python3
# -*- coding: UTF-8 -*-

import json
import argparse
import datetime
from urllib import parse
import listparser
import feedparser
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml

from bot import *
from utils import *

import requests
requests.packages.urllib3.disable_warnings()

today = datetime.datetime.now().strftime("%Y-%m-%d")
yesterday = str(datetime.date.today() + datetime.timedelta(-1))
root_path = Path(__file__).absolute().parent


def update_today(data: dict= {}):
    """更新today"""
    data_path = root_path.joinpath(f'archive/tmp/{today}.json')
    today_path = root_path.joinpath('today.md')
    archive_path = root_path.joinpath(f'archive/daily/{today.split("-")[0]}/{today}.md')

    if not data and data_path.exists():
        with open(data_path, 'r', encoding="utf-8") as f1:
            data = json.load(f1)

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(today_path, 'w+', encoding="utf-8") as f1, open(archive_path, 'w+', encoding="utf-8") as f2:
        content = f'# 每日安全资讯（{today}）\n\n'
        for feed, articles in data.items():
            content += f'- {feed}\n'
            for title, url in articles.items():
                content += f'  - [ ] [{title}]({url})\n'
        f1.write(content)
        f2.write(content)


def update_rss(rss: dict, proxy_url=''):
    """更新订阅源文件"""
    proxy = {'http': proxy_url, 'https': proxy_url} if proxy_url else {'http': None, 'https': None}

    (key, value), = rss.items()
    rss_path = root_path.joinpath(f'rss/{value["filename"]}')

    result = None
    if url := value.get('url'):
        r = requests.get(value['url'], proxies=proxy)
        if r.status_code == 200:
            with open(rss_path, 'w+', encoding="utf-8") as f:
                f.write(r.text)
            print(f'[+] 更新完成：{key}')
            result = {key: rss_path}
        elif rss_path.exists():
            print(f'[-] 更新失败，使用旧文件：{key}')
            result = {key: rss_path}
        else:
            print(f'[-] 更新失败，跳过：{key}')
    else:
        print(f'[+] 本地文件：{key}')

    return result


def update_pick():
    yesterday_issues = json.loads(popen(f"gh issue list --label \"pick\" --search \"{yesterday}\" --json title,url,author,body"))
    today_path = root_path.joinpath('today_pick.md')
    if not yesterday_issues:
        console.print("not found any picker articles", style='bold yellow')
        for bot in picker_bots:
            bot.send_raw(f"[{yesterday} 精选汇总]", f"昨日({yesterday})没有精选文章, 别忘了阅读[每日信息流]({conf['repo']}/issues), 并点击`convert to issue` 挑选优质文章^v^")
        with open(today_path, "w+", encoding="utf-8") as f:
            f.write(f"昨日({yesterday})没有精选文章")
        return

    archive_path = root_path.joinpath(f'archive/daily_pick/{yesterday.split("-")[0]}/{yesterday}.md')
    data_path = root_path.joinpath(f'archive/tmp/{yesterday}.json')
    data = {}
    if data_path.exists():
        with open(data_path, 'r', encoding="utf-8") as f1:
            data = json.load(f1)

    picker = {}
    for issue in yesterday_issues:
        found = False
        issue_title = issue["title"].lstrip(f"[{yesterday}] ").strip()
        for feed, articles in data.items():
            for title, link in articles.items():
                if issue_title == title:
                    found = True
                    if not picker.get(feed, ""):
                        picker[feed] = []
                    picker[feed].append((f"[{title}]({link})", issue["url"]))
        if not found:
            custom_feed = f"{issue['author']['login']} 手动精选"
            if not picker.get(custom_feed, ""):
                picker[custom_feed] = []
            title = issue["title"].lstrip(f"[{yesterday}]").strip()
            picker[custom_feed].append((f'[{title}]({issue["body"]})', issue["url"]))

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with open(today_path, 'w+', encoding="utf-8") as f1, open(archive_path, 'w+', encoding="utf-8") as f2:
        content = f'# 昨日精选汇总（{yesterday}）\n\n'
        for feed, articles in picker.items():
            content += f'- {feed}\n\n'
            for link, issue_url in articles:
                content += f'  - {link} - [discussion]({issue_url})\n'

        f1.write(content)
        f2.write(content)

        for bot in picker_bots:
            bot.send_raw(f"[{yesterday} 精选汇总]", content)


def push_issue(issue_number):
    issue = json.loads(popen(f"gh issue view {issue_number} --json title,url,author,body"))
    issue_title = issue["title"].lstrip(f"[{today}]").strip()
    success = False
    data_path = root_path.joinpath(f'archive/tmp/{today}.json')
    if data_path.exists():
        with open(data_path, 'r', encoding="utf-8") as f1:
            data = json.load(f1)

        for feed, articles in data.items():
            for title, link in articles.items():
                if title == issue_title:
                    success = True

    return success


def get_feed(rss_path, proxy_url=''):
    """获取订阅源"""
    proxy = {'http': proxy_url, 'https': proxy_url} if proxy_url else {'http': None, 'https': None}

    result = {}
    rss = listparser.parse(str(rss_path))
    feeds = rss.feeds

    def fetch(feed):
        title = feed.title
        url = feed.url
        try:
            r = feedparser.parse(url, request_headers={'User-Agent': 'Mozilla/5.0'})
            articles = {}
            for entry in r.entries:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime.datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
                    if pub_date == today:
                        articles[entry.title] = entry.link
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime.datetime(*entry.updated_parsed[:6]).strftime("%Y-%m-%d")
                    if pub_date == today:
                        articles[entry.title] = entry.link
            if articles:
                return {title: articles}
        except Exception as e:
            console.print(f'[-] 获取失败：{title} {e}', style='bold red')
        return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch, feed): feed for feed in feeds}
        for future in as_completed(futures):
            res = future.result()
            if res:
                result.update(res)

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update-rss', action='store_true', help='更新订阅源文件')
    parser.add_argument('--update-today', action='store_true', help='更新today.md')
    parser.add_argument('--update-pick', action='store_true', help='更新精选')
    parser.add_argument('--push-issue', type=int, help='推送issue')
    parser.add_argument('--proxy', type=str, default='', help='代理地址')
    args = parser.parse_args()

    if args.update_rss:
        rss_config_path = root_path.joinpath('rss/rss.yml')
        with open(rss_config_path, 'r', encoding='utf-8') as f:
            rss_config = yaml.safe_load(f)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_rss, {k: v}, args.proxy) for k, v in rss_config.items()]
            for future in as_completed(futures):
                future.result()

    elif args.update_today:
        update_today()

    elif args.update_pick:
        update_pick()

    elif args.push_issue:
        push_issue(args.push_issue)

    else:
        # Default: fetch feeds and update today
        rss_config_path = root_path.joinpath('rss/rss.yml')
        if not rss_config_path.exists():
            console.print('[-] rss.yml not found', style='bold red')
            return

        with open(rss_config_path, 'r', encoding='utf-8') as f:
            rss_config = yaml.safe_load(f)

        rss_paths = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(update_rss, {k: v}, args.proxy): k for k, v in rss_config.items()}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    rss_paths.update(res)

        data = {}
        for name, rss_path in rss_paths.items():
            feeds = get_feed(rss_path, args.proxy)
            data.update(feeds)

        data_path = root_path.joinpath(f'archive/tmp/{today}.json')
        data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(data_path, 'w+', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        update_today(data)

        for bot in bots:
            today_path = root_path.joinpath('today.md')
            with open(today_path, 'r', encoding='utf-8') as f:
                content = f.read()
            bot.send_raw(f'[{today} 每日信息流]', content)


if __name__ == '__main__':
    main()