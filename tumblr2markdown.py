#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pytumblr
from datetime import datetime  # for strptime
import re
import os
import codecs
import argparse
import hashlib  # for image URL->path hashing
from urllib.request import urlopen
import html2text

def processPostBodyForImages(postBody, imagesPath, imagesUrlPath):
    # Coding pattern recommended by http://docs.python.org/2/faq/design.html#why-can-t-i-use-an-assignment-in-an-expression
    tumblrImageUrl = re.compile(r"(https?://[0-z.]+tumblr\.com/[0-z_/]+(tumblr_inline[0-z_]+\.(?:jpe?g|png|gif)))")

    # Create the image folder if it does not exist
    if not os.path.exists(imagesPath):
        os.makedirs(imagesPath)

    matches = re.findall(tumblrImageUrl, postBody)

    for imageMatch in matches:
        concreteImageUrl = imageMatch[0]
        concreteImageName = imageMatch[1]

        concreteImagePath = os.path.join(imagesPath, concreteImageName)
        imageOutputUrlPath = os.path.join(imagesUrlPath, concreteImageName)
        # Assumes that all images are downloaded in full by httpclient, does not check for file integrity
        if not os.path.exists(concreteImagePath):
            # Download the image and then replace the URL in body
            imageContent = urlopen(concreteImageUrl).read()
            f = open(concreteImagePath, 'wb')
            f.write(imageContent)
            f.close()

        postBody = postBody.replace(concreteImageUrl, imageOutputUrlPath)

    return postBody


def downloader(apiKey, host, postsPath, downloadImages, imagesPath, imagesUrlPath):
    # Authenticate via API Key
    client = pytumblr.TumblrRestClient(apiKey)

    # http://www.tumblr.com/docs/en/api/v2#posts

    # Make the request

    processed = 0
    total_posts = 1

    posts_per_type = {}

    while processed < total_posts:
        response = client.posts(host, limit=20, offset=processed, filter='raw')
        total_posts = response['total_posts']
        posts = response['posts']
        processed += len(posts)

        print("Processing...")
        for post in posts:
            print("	http://" + host + "/post/" + str(post["id"]))

            try:
                posts_per_type[post['type']] += 1
            except KeyError:
                posts_per_type[post['type']] = 1
            # 2011-12-13 17:00:00 GMT
            postDate = datetime.strptime(post["date"], "%Y-%m-%d %H:%M:%S %Z")

            body = ""

            if post['type'] == 'text':
                post["tags"].append("text")
                title = post["title"]
                body = body + post["body"]

            elif post["type"] == "photo":
                title = post["summary"]
                post["tags"].append("photo")
                for photo in post["photos"]:
                    body = body + "<img src='" + photo["original_size"]["url"] + "'/>" #+ post["caption"]

            elif post["type"] == "video":
                title = post["summary"]
                post["tags"].append("video")

                # todo, assuming youtube need to export shortcode like {{ youtube(id="WJ02eSfGmMQ") }}
                body = body + '<a href="' + post["permalink_url"]   + '"><img alt="'+ post["summary"] +'" src="' + post["thumbnail_url"]+'"></a>'

            #no thanks
            elif post["type"] == "link":
                print("unhandled link post", post)
                continue
            elif post["type"] == "quote":
                print("unhandled quote post", post)
                continue
            else:
                print("unhandled unknown type", post)
                continue


            # Download images if requested
            if downloadImages:
                body = processPostBodyForImages(body, imagesPath, imagesUrlPath)

            # We have completely processed the post and the Markdown is ready to be output

            slug = post["slug"]

            # If path does not exist, make it
            if not os.path.exists(postsPath):
                os.makedirs(postsPath)

            f = codecs.open(findFileName(postsPath, slug), encoding='utf-8', mode="w+")

            tags = ""
            if len(post["tags"]):
                tags = ', '.join('"{0}"'.format(w) for w in post["tags"])

            # html2text strips bad looking tags like our more
            body = body.replace("<!-- more -->","[[MORE]]")

            # Otherwise it line breaks inside of links and other markdown structures
            text_maker = html2text.HTML2Text()
            text_maker.body_width = 0
            body = text_maker.handle(body)

            # now bring it back
            body = body.replace("[[MORE]]", "<!-- more -->")


            f.write(
                "+++\n" +
                "date = " + postDate.isoformat('T') + ".000Z\n" +
                "title = \"" + title.replace('"','\\"') + "\"\n" +
                "draft = false\n" +
                "in_search_index = true\n" +
                "aliases = [\"/post/" + str(post["id"]) + "/" + post["slug"]+  "\", " +
                "\"/post/" + post["slug"]+  "\"]\n" +
                "[taxonomies]\n" +
                "tags = [" + tags + "]\n" +
                "+++\n\n" +
                body)

            f.close()

        print("Processed", processed, "out of", total_posts, "posts")

    print("Posts per type:", posts_per_type)


def findFileName(path, slug):
    """Make sure the file doesn't already exist"""
    for attempt in range(0, 99):
        file_name = makeFileName(path, slug, attempt)
        if not os.path.exists(file_name):
            return file_name

    print("ERROR: Too many clashes trying to create filename " + makeFileName(path, slug))
    exit()


def makeFileName(path, slug, exists=0):
    suffix = "" if exists == 0 else "-" + str(exists + 1)
    return os.path.join(path, slug) + suffix + ".md"


def main():
    parser = argparse.ArgumentParser(description="Tumblr to Markdown downloader",
                                     epilog="""
		This app downloads all your Tumblr content into Markdown files that are suitable for processing with Octopress. Optionally also downloads the images hosted on Tumblr and replaces their URLs with locally hosted versions.
		""")
    parser.add_argument('--apikey', dest="apiKey", required=True, help="Tumblr API key")
    parser.add_argument('--host', dest="host", required=True, help="Tumblr site host, e.g example.tumblr.com")
    parser.add_argument('--posts-path', dest="postsPath", default="_posts",
                        help="Output path for posts, by default “_posts”")
    parser.add_argument('--download-images', dest="downloadImages", action="store_true",
                        help="Whether to download images hosted on Tumblr into a local folder, and replace their URLs in posts")
    parser.add_argument('--images-path', dest="imagesPath", default="images",
                        help="If downloading images, store them to this local path, by default “images”")
    parser.add_argument('--images-url-path', dest="imagesUrlPath", default="/images",
                        help="If downloading images, this is the URL path where they are stored at, by default “/images”")

    args = parser.parse_args()

    if not args.apiKey:
        print("Tumblr API key is required.")
        exit(0)

    if not args.host:
        print("Tumblr host name is required.")
        exit(0)

    downloader(args.apiKey, args.host, args.postsPath, args.downloadImages, args.imagesPath, args.imagesUrlPath)


if __name__ == "__main__":
    main()
