from django.template.defaultfilters import urlizetrunc
from django.test import SimpleTestCase
from django.utils.safestring import mark_safe

from ..utils import render, setup


class UrlizetruncTests(SimpleTestCase):

    @setup({'urlizetrunc01':
        '{% autoescape off %}{{ a|urlizetrunc:"8" }} {{ b|urlizetrunc:"8" }}{% endautoescape %}'})
    def test_urlizetrunc01(self):
        output = render(
            'urlizetrunc01',
            {
                'a': '"Unsafe" http://example.com/x=&y=',
                'b': mark_safe('&quot;Safe&quot; http://example.com?x=&amp;y='),
            },
        )
        self.assertEqual(
            output,
            '"Unsafe" <a href="http://example.com/x=&y=" rel="nofollow">http:...</a> '
            '&quot;Safe&quot; <a href="http://example.com?x=&y=" rel="nofollow">http:...</a>'
        )

    @setup({'urlizetrunc02': '{{ a|urlizetrunc:"8" }} {{ b|urlizetrunc:"8" }}'})
    def test_urlizetrunc02(self):
        output = render(
            'urlizetrunc02',
            {
                'a': '"Unsafe" http://example.com/x=&y=',
                'b': mark_safe('&quot;Safe&quot; http://example.com?x=&amp;y='),
            },
        )
        self.assertEqual(
            output,
            '&quot;Unsafe&quot; <a href="http://example.com/x=&y=" rel="nofollow">http:...</a> '
            '&quot;Safe&quot; <a href="http://example.com?x=&y=" rel="nofollow">http:...</a>'
        )


class FunctionTests(SimpleTestCase):

    def test_truncate(self):
        uri = 'http://31characteruri.com/test/'
        self.assertEqual(len(uri), 31)

        self.assertEqual(
            urlizetrunc(uri, 31),
            '<a href="http://31characteruri.com/test/" rel="nofollow">'
            'http://31characteruri.com/test/</a>',
        )

        self.assertEqual(
            urlizetrunc(uri, 30),
            '<a href="http://31characteruri.com/test/" rel="nofollow">'
            'http://31characteruri.com/t...</a>',
        )

        self.assertEqual(
            urlizetrunc(uri, 2),
            '<a href="http://31characteruri.com/test/"'
            ' rel="nofollow">...</a>',
        )

    def test_overtruncate(self):
        self.assertEqual(
            urlizetrunc('http://short.com/', 20), '<a href='
            '"http://short.com/" rel="nofollow">http://short.com/</a>',
        )

    def test_query_string(self):
        self.assertEqual(
            urlizetrunc('http://www.google.co.uk/search?hl=en&q=some+long+url&btnG=Search&meta=', 20),
            '<a href="http://www.google.co.uk/search?hl=en&q=some+long+url&btnG=Search&'
            'meta=" rel="nofollow">http://www.google...</a>',
        )

    def test_non_string_input(self):
        self.assertEqual(urlizetrunc(123, 1), '123')
