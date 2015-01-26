from __future__ import absolute_import, division, print_function

import json
from toolz.curried import map, take, pipe, pluck, get, concat, filter
from collections import Iterator, Iterable
import os
from contextlib import contextmanager

from datashape import discover, var, dshape, Record, DataShape
from datashape import coretypes as ct
from datashape.dispatch import dispatch
import gzip
import datetime
from ..append import append
from ..convert import convert, ooc_types
from ..resource import resource
from ..chunks import chunks
from ..utils import tuples_to_records


class JSON(object):
    """ Proxy for a JSON file

    Parameters
    ----------

    path : str
        Path to file on disk

    See Also
    --------

    JSONLines - Line-delimited JSON
    """
    def __init__(self, path):
        self.path = path


class JSONLines(object):
    """ Proxy for a line-delimited JSON file

    Each line in the file is a valid JSON entry

    Parameters
    ----------

    path : str
        Path to file on disk

    See Also
    --------

    JSON - Not-line-delimited JSON
    """
    def __init__(self, path):
        self.path = path


def date_to_datetime_dshape(ds):
    shape = ds.shape
    if isinstance(ds.measure, Record):
        measure = Record([[name, ct.datetime_ if typ == ct.date_ else typ]
            for name, typ in ds.measure.parameters[0]])
    else:
        measure = ds.measure
    return DataShape(*(shape + (measure,)))


@discover.register(JSON)
def discover_json(j, **kwargs):
    data = json_load(j.path)
    ds = discover(data)
    return date_to_datetime_dshape(ds)


def nonempty(line):
    return len(line.strip()) > 0


@discover.register(JSONLines)
def discover_jsonlines(j, n=10, encoding='utf-8', **kwargs):
    with json_lines(j.path, encoding=encoding) as lines:
        data = pipe(lines, filter(nonempty), map(json.loads), take(n), list)

    if len(data) < n:
        ds = discover(data)
    else:
        ds = var * discover(data).subshape[0]
    return date_to_datetime_dshape(ds)



@convert.register(list, JSON)
def json_to_list(j, dshape=None, **kwargs):
    return json_load(j.path, **kwargs)


@convert.register(Iterator, JSONLines)
def json_lines_to_iterator(j, encoding='utf-8', **kwargs):
    with json_lines(j.path, encoding=encoding) as lines:
        for item in pipe(lines, filter(nonempty), map(json.loads)):
            yield item


@contextmanager
def json_lines(path, encoding='utf-8'):
    """ Return lines of a json-lines file

    Handles compression like gzip """
    if path.split(os.path.extsep)[-1] == 'gz':
        f = gzip.open(path)
        lines = (line.decode(encoding) for line in f)
    else:
        f = open(path)
        lines = f

    try:
        yield lines
    finally:
        f.close()


def json_load(path, encoding='utf-8', **kwargs):
    """ Return data of a json file

    Handles compression like gzip """
    if path.split(os.path.extsep)[-1] == 'gz':
        f = gzip.open(path)
        s = f.read().decode(encoding)
    else:
        f = open(path)
        s = f.read()

    data = json.loads(s)

    f.close()

    return data


@append.register(JSONLines, object)
def object_to_jsonlines(j, o, **kwargs):
    return append(j, convert(Iterator, o, **kwargs), **kwargs)


@append.register(JSONLines, Iterator)
def iterator_to_json_lines(j, seq, dshape=None, **kwargs):
    row = next(seq)
    seq = concat([[row], seq])
    if not isinstance(row, (dict, str)) and isinstance(row, Iterable):
        seq = tuples_to_records(dshape, seq)
    with open(j.path, 'a') as f:
        for item in seq:
            json.dump(item, f, default=json_dumps)
            f.write('\n')
    return j


@append.register(JSON, list)
def list_to_json(j, seq, dshape=None, **kwargs):
    if not isinstance(seq[0], (dict, str)) and isinstance(seq[0], Iterable):
        seq = list(tuples_to_records(dshape, seq))
    if os.path.exists(j.path):
        with open(j.path) as f:
            if json.load(f):
                raise ValueError("Can only append to empty JSON File.\n"
                "Either remove contents from this file, save to a new file \n"
                "or use line-delimited JSON format.\n"
                "Consider using the jsonlines:// protocol, e.g.\n"
                "\tinto('jsonlines://%s', your-data)" % j.path)

    with open(j.path, 'w') as f:
        json.dump(seq, f, default=json_dumps)
    return j


@append.register(JSON, object)
def object_to_json(j, o, **kwargs):
    return append(j, convert(list, o, **kwargs), **kwargs)


@resource.register('json://.*\.json', priority=11)
def resource_json(path, **kwargs):
    if 'json://' in path:
        path = path[len('json://'):]
    return JSON(path)


@resource.register('.*\.jsonlines', priority=11)
@resource.register('jsonlines://.*\.json', priority=11)
def resource_jsonlines(path, **kwargs):
    if 'jsonlines://' in path:
        path = path[len('jsonlines://'):]
    return JSONLines(path)


@resource.register('.*\.json')
def resource_json_ambiguous(path, **kwargs):
    """ Try to guess if this file is line-delimited or not """
    if os.path.exists(path):
        f = open(path)
        one = next(f)
        try:
            two = next(f)
        except StopIteration:  # only one line
            f.close()
            return resource_json(path, **kwargs)
        try:
            json.loads(one)
            f.close()
            return resource_jsonlines(path, **kwargs)
        except:
            f.close()
            return resource_json(path, **kwargs)

    # File doesn't exist, is the dshape variable length?
    dshape = kwargs.get('expected_dshape', None)
    if dshape and dshape[0] == var:
        return resource_jsonlines(path, **kwargs)
    else:
        return resource_json(path, **kwargs)


@dispatch(datetime.datetime)
def json_dumps(dt):
    s = dt.isoformat()
    if not dt.tzname():
        s = s + 'Z'
    return s


@dispatch(datetime.date)
def json_dumps(dt):
    return dt.isoformat()


@convert.register(chunks(list), chunks(JSON))
def convert_glob_of_jsons_into_chunks_of_lists(jsons, **kwargs):
    def _():
        return concat(convert(chunks(list), js, **kwargs) for js in jsons)
    return chunks(list)(_)


@convert.register(chunks(Iterator), chunks(JSONLines))
def convert_glob_of_jsons_into_chunks_of_lists(jsons, **kwargs):
    def _():
        return concat(convert(chunks(Iterator), js, **kwargs) for js in jsons)
    return chunks(Iterator)(_)


ooc_types.add(JSONLines)
