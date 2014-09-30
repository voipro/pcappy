#!/usr/bin/env python

import sys
from ctypes import POINTER, pointer
from socket import *
from struct import pack, unpack
from binascii import hexlify

from constants import *
from functions import *


__author__ = 'Nadeem Douba'
__copyright__ = 'Copyright 2012, PcapPy Project'
__credits__ = ['Nadeem Douba']

__license__ = 'GPL'
__version__ = '0.3'
__maintainer__ = 'Nadeem Douba'
__email__ = 'ndouba@gmail.com'
__status__ = 'Development'

__all__ = [
    'PcapPyLive',
    'PcapPyOffline',
    'PcapPyDead',
    'open_offline',
    'open_dead',
    'open_live',
    'findalldevs',
    'PcapPyException'
]


def _inet_ntoa(ip):
    return inet_ntop(AF_INET, pack('!L', htonl(ip)))


def _inet6_ntoa(ip):
    return inet_ntop(AF_INET6, ip)


def _inet_atoi(ip):
    return htonl(unpack('!L', inet_aton(ip))[0])


class PcapPyException(Exception):
    pass


class PcapPyInterface(object):

    def __init__(self, pa):

        self._addresses = []
        self._name = pa.name
        self._description = pa.description or ''
        self._flags = pa.flags

        topaddr = pa.addresses

        while topaddr:
            topaddr = topaddr.contents

            self.addresses.append(
                dict(
                    addr=self._parseaddrs(topaddr.addr),
                    netmask=self._parseaddrs(topaddr.netmask),
                    broadaddr=self._parseaddrs(topaddr.broadaddr),
                    dstaddr=self._parseaddrs(topaddr.dstaddr)
                )
            )

            topaddr = topaddr.next

    @property
    def addresses(self):
        return self._addresses

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def flags(self):
        return self._flags

    def _parsemac(self, mac):
        return ':'.join([ hexlify(i).zfill(2) for i in mac ])


    def _parseaddrs(self, sa):

        if not sa:
            return
        sa = sa.contents

        if sa.sa.sa_family == AF_LINK:
            return dict(
                sdl_len=sa.sdl.sdl_len,
                sdl_family=sa.sdl.sdl_family,
                sdl_index=sa.sdl.sdl_index,
                sdl_type=sa.sdl.sdl_type,
                sdl_nlen=sa.sdl.sdl_nlen,
                sdl_alen=sa.sdl.sdl_alen,
                sdl_slen=sa.sdl.sdl_slen,
                sdl_data=self._parsemac(string_at(byref(sa.sdl.sdl_data, sa.sdl.sdl_nlen), sa.sdl.sdl_alen))
            )
        elif sa.sa.sa_family == AF_PACKET:
            return dict(
                sll_family=sa.sll.sll_family,
                sll_protocol=sa.sll.sll_protocol,
                sll_ifindex=sa.sll.sll_ifindex,
                sll_hatype=sa.sll.sll_hatype,
                sll_pkttype=sa.sll.sll_pkttype,
                sll_halen=sa.sll.sll_halen,
                sll_data=self._parsemac(string_at(byref(sa.sll.sll_data), sa.sll.sll_halen))
            )
        elif sa.sa.sa_family == AF_INET:
            if platform == 'darwin':
                return dict(
                    len=sa.sin.sin_len,
                    family=sa.sin.sin_family,
                    port=sa.sin.sin_port,
                    address=_inet_ntoa(sa.sin.sin_addr)
                )
            else:
                return dict(
                    family=sa.sin.sin_family,
                    port=sa.sin.sin_port,
                    address=_inet_ntoa(sa.sin.sin_addr)
                )
        elif sa.sa.sa_family == AF_INET6:
            if platform == 'darwin':
                return dict(
                    len=sa.sin6.sin6_len,
                    port=sa.sin6.sin6_port,
                    family=sa.sin6.sin6_family,
                    flowinfo=sa.sin6.sin6_flowinfo,
                    address=_inet6_ntoa(string_at(sa.sin6.sin6_addr, 16)),
                    scope_id=sa.sin6.sin6_scope_id
                )
            else:
                return dict(
                    port=sa.sin6.sin6_port,
                    family=sa.sin6.sin6_family,
                    flowinfo=sa.sin6.sin6_flowinfo,
                    address=_inet6_ntoa(string_at(sa.sin6.sin6_addr, 16)),
                    scope_id=sa.sin6.sin6_scope_id
                )
        if platform == 'darwin':
            return dict(
                len=sa.sa.sa_len,
                family=sa.sa.sa_family,
                data=string_at(sa.sa.sa_data, sa.sa.sa_len)
            )
        else:
            return dict(
                family=sa.sa.sa_family,
                data=string_at(sa.sa.sa_data, sa.sa.sa_len)
            )


class PcapPyDumper(object):

    def __init__(self, pcap, file_, ng=False):
        self._pcap = pcap
        self.filename = file_
        self._pd = None
        self._ng = ng
        if self._ng:
            if isinstance(file_, file):
                self._pd = pcap_ng_dump_fopen(self._pcap._p, PyFile_AsFile(file_))
            else:
                self._pd = pcap_ng_dump_open(self._pcap._p, self.filename)
        else:
            if isinstance(file_, file):
                self._pd = pcap_dump_fopen(self._pcap._p, PyFile_AsFile(file_))
            else:
                self._pd = pcap_dump_open(self._pcap._p, self.filename)
        if not self._pd:
            raise PcapPyException(self._pcap.err)

    def close(self):
        if not self.closed:
            self.flush()
            if self._ng:
                pcap_ng_dump_close(self._pd)
            else:
                pcap_dump_close(self._pd)
            self._pd = None

    def tell(self):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        r = pcap_dump_ftell(self._pd)
        if r == -1:
            raise PcapPyException(self._pcap.err)
        return r

    ftell = tell

    def flush(self):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        r = pcap_dump_flush(self._pd)
        if r == -1:
            raise PcapPyException(self._pcap.err)

    def write(self, pkt_hdr, pkt_data):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        ph = pcap_pkthdr(
            ts=timeval(
                tv_sec=pkt_hdr['ts']['tv_sec'],
                tv_usec=pkt_hdr['ts']['tv_usec']
            ),
            caplen=pkt_hdr['caplen'],
            len=pkt_hdr['len']
        )
        if self._ng:
            pcap_ng_dump(self._pd, pointer(ph), pkt_data)
        else:
            pcap_dump(self._pd, pointer(ph), pkt_data)

    dump = ng_dump = write

    def fileno(self):
        return self.file.fileno()

    @property
    def file(self):
        if self.closed:
            raise ValueError('I/O operation on closed file')
        f = pcap_dump_file(self._pd)
        if not f:
            raise PcapPyException(self._pcap.err)
        return PyFile_FromFile(f, self.filename, 'wb', None)

    @property
    def closed(self):
        return self._pd is None

    def __del__(self):
        self.close()


class PcapPyBpfProgram(object):

    def __init__(self, expr, opt, nm, **kwargs):
        self._expression = expr
        self._optimize = opt
        self._netmask = nm
        self._bpf = bpf_program()
        if 'pcap' in kwargs:
            if pcap_compile(kwargs['pcap']._p, pointer(self._bpf), expr, opt, _inet_atoi(nm)) == -1:
                raise PcapPyException(kwargs['pcap'].err)
        elif pcap_compile_nopcap(kwargs['snaplen'], kwargs['linktype'], pointer(self._bpf), expr, opt, _inet_atoi(nm)) == -1:
                raise PcapPyException(kwargs['pcap'].err)

    @property
    def expression(self):
        return self._expression

    @property
    def optimize(self):
        return self._optimize

    @property
    def netmask(self):
        return self._netmask

    mask = netmask

    def __del__(self):
        if self._bpf:
            pcap_freecode(pointer(self._bpf))


def open_live(device, snaplen=64, promisc=1, to_ms=1000):
    return PcapPyLive(device, snaplen, promisc, to_ms)


def open_dead(linktype=LINKTYPE_ETHERNET, snaplen=64):
    return PcapPyDead(linktype, snaplen)


def open_offline(file):
    return PcapPyOffline(file)


def _findalldevs(devs):
    top = devs
    devices = []

    while top:
        top = top.contents
        devices.append(PcapPyInterface(top))
        top = top.next

    pcap_freealldevs(devs)

    return devices


def findalldevs():
    errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
    devs = pcap_if_t_ptr()

    if pcap_findalldevs(pointer(devs), c_char_p((addressof(errbuf)))) == -1:
        raise PcapPyException(errbuf.raw)

    return _findalldevs(devs)


def findalldevs_ex(source, username='', password=''):
    errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
    ra = pcap_rmtauth()
    ra.type = RPCAP_RMTAUTH_PWD if username and password else RPCAP_RMTAUTH_NULL
    ra.username = username
    ra.password = password

    devs = pcap_if_t_ptr()

    if pcap_findalldevs_ex(source, pointer(ra), pointer(devs), c_char_p((addressof(errbuf)))) == -1:
        raise PcapPyException(errbuf.raw)

    return _findalldevdevs(devs)


def lookupdev():
    errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
    r = pcap_lookupdev(c_char_p((addressof(errbuf))))
    if not r:
        raise PcapPyException(errbuf.raw)
    return r


def datalink_val_to_name(val):
    return pcap_datalink_val_to_name(val)


def datalink_name_to_val(name):
    return pcap_datalink_name_to_val(name)


def datalink_val_to_description(val):
    return pcap_datalink_val_to_description(val)


def lookupnet(device):
    errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
    netp = c_uint32()
    maskp = c_uint32()

    r = pcap_lookupnet(
        device,
        pointer(netp),
        pointer(maskp),
        c_char_p(addressof(errbuf))
    )
    if r == -1:
        raise PcapPyException(errbuf.raw)
    return _inet_ntoa(netp.value), _inet_ntoa(maskp.value)


def statustostr(status):
    return pcap_statustostr(status)


def strerror(status):
    return pcap_strerror(status)


def compile_nopcap(snaplen=64, linktype=LINKTYPE_ETHERNET, expr='', optimize=1, mask='0.0.0.0'):
    return PcapPyBpfProgram(expr, optimize, mask, linktype=linktype, snaplen=snaplen)


class PcapPyBase(object):

    _is_base = True

    def __init__(self):
        if self._is_base:
            raise Exception('Cannot initialize base class. Use PcapPyLive, PcapPyDead, or PcapPyOffline instead.')
        self._p = None
        self._bpf = None

    @classmethod
    def findalldevs(cls):
        return findalldevs()

    @classmethod
    def findalldevs_ex(cls, source, username='', password=''):
        return findalldevs_ex(source, username, password)

    def geterr(self):
        return self.err

    @classmethod
    def lookupdev(self):
        return lookupdev

    def list_datalinks(self):
        dlt_buf = c_int_p()

        r = pcap_list_datalinks(self._p, pointer(dlt_buf))

        if r == -1:
            raise PcapPyException(self.err)

        dlt_buf_a = cast(dlt_buf, POINTER(c_int * r)).contents

        l = [ dlt_buf_a[i] for i in range(0, r) ]

        pcap_free_datalinks(dlt_buf)

        return l

    @classmethod
    def datalink_val_to_name(cls, val):
        return datalink_val_to_name(val)

    @classmethod
    def datalink_name_to_val(cls, name):
        return datalink_name_to_val(name)

    @classmethod
    def datalink_val_to_description(cls, val):
        return datalink_val_to_description(val)

    @classmethod
    def lookupnet(cls, device):
        return lookupnet(device)

    def compile(self, expr, optimize=1, mask='0.0.0.0'):
        return PcapPyBpfProgram(expr, optimize, mask, pcap=self)

    def dump_open(self, filename):
        return PcapPyDumper(self, filename)

    @classmethod
    def compile_nopcap(cls, snaplen=64, linktype=LINKTYPE_ETHERNET, expr='', optimize=1, mask='0.0.0.0'):
        return compile_nopcap(snaplen, linktype, expr, optimize, mask)

    @classmethod
    def statustostr(cls, status):
        return statustostr(status)

    @classmethod
    def strerror(cls, status):
        return strerror(status)

    @property
    def is_swapped(self):
        return pcap_is_swapped(self._p) == 1

    @property
    def minor_version(self):
        return pcap_minor_version(self._p)

    @property
    def major_version(self):
        return pcap_major_version(self._p)

    @property
    def lib_version(self):
        return pcap_lib_version(self._p)

    @property
    def err(self):
        return pcap_geterr(self._p)

    @property
    def datalink_ext(self):
        r = pcap_datalink_ext(self._p)
        if r == -1:
            raise PcapPyException(self.err)
        return r

    def get_datalink(self):
        r = pcap_datalink(self._p)
        if r == -1:
            raise PcapPyException(self.err)
        return r

    def set_datalink(self, value):
        if pcap_set_datalink(self._p, value) < 0:
            raise PcapPyException(self.err)

    datalink = property(get_datalink, set_datalink)

    def get_snapshot(self):
        return pcap_snapshot(self._p)

    def set_snapshot(self, value):
        if pcap_set_snaplen(self._p, value) < 0:
            raise PcapPyException(self.err)

    snapshot = property(get_snapshot, set_snapshot)

    snaplen = snapshot

    def __del__(self):
        if self._p:
            pcap_close(self._p)


class PcapPyDead(PcapPyBase):

    _is_base = False

    def __init__(self, linktype=LINKTYPE_ETHERNET, snaplen=64):
        super(PcapPyDead, self).__init__()
        errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
        self._p = pcap_open_dead(linktype, snaplen)
        if not self._p:
            raise PcapPyException(errbuf.raw)


class PcapPyAlive(PcapPyBase):

    def __init__(self):
        super(PcapPyAlive, self).__init__()
        self._direction = 0

    def _parse_entry(self, ph, pd):
        if platform == 'darwin':
            return dict(
                caplen=ph.caplen,
                len=ph.len,
                ts=dict(tv_usec=ph.ts.tv_usec, tv_sec=ph.ts.tv_sec),
                comments=string_at(ph.comments)
            ), string_at(pd, ph.caplen)

        return dict(
            caplen=ph.caplen,
            len=ph.len,
            ts=dict(tv_usec=ph.ts.tv_usec, tv_sec=ph.ts.tv_sec)
        ), string_at(pd, ph.caplen)

    def _setup_handler(self, looper, cnt, callback, user):
        def _loop_callback(user, ph, pd):
            ph, pd = self._parse_entry(ph.contents, pd)
            callback(user.contents.value, ph, pd)

        r = looper(self._p, cnt, pcap_handler(_loop_callback), pointer(py_object(user)))
        if r == -1:
            raise PcapPyException(self.err)
        return r

    def loop(self, cnt, callback, user):
        return self._setup_handler(pcap_loop, cnt, callback, user)

    def dispatch(self, cnt, callback, user):
        return self._setup_handler(pcap_dispatch, cnt, callback, user)

    def breakloop(self):
        pcap_breakloop(self._p)

    def next_ex(self):
        ph = pcap_pkthdr_ptr()
        pd = c_ubyte_p()

        r = pcap_next_ex(self._p, pointer(ph), pointer(pd))

        if r in [0, -2]:
            return None
        elif r == -1:
            raise PcapPyException(self.err)

        return self._parse_entry(ph.contents, pd)

    def next(self):
        ph = pcap_pkthdr()
        pd = pcap_next(self._p, pointer(ph))

        if not pd:
            return None

        return self._parse_entry(ph, pd)

    def get_nonblock(self):
        errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
        r = pcap_getnonblock(self._p, c_char_p((addressof(errbuf))))
        if r == -1:
            raise PcapPyException(errbuf.raw)
        return r

    def set_nonblock(self, value):
        errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
        r = pcap_setnonblock(self._p, value, c_char_p((addressof(errbuf))))
        if r < 0:
            raise PcapPyException(errbuf.raw)

    nonblock = property(get_nonblock, set_nonblock)

    @property
    def stats(self):
        ps = pcap_stat()

        if pcap_stats(self._p, pointer(ps)):
            raise PcapPyException(self.err)

        if platform == 'nt':
            return dict(
                ps_recv=ps.ps_recv,
                ps_drop=ps.ps_drop,
                ps_ifdrop=ps.ps_ifdrop,
                bs_capt=ps.bs_capt
            )

        return dict(
            ps_recv=ps.ps_recv,
            ps_drop=ps.ps_drop,
            ps_ifdrop=ps.ps_ifdrop
        )

    def get_filter(self):
        return self._bpf

    def set_filter(self, value):
        if isinstance(value, basestring):
            self._bpf = self.compile(value)
        else:
            self._bpf = value
        if pcap_setfilter(self._p, pointer(self._bpf._bpf)) < 0:
            raise PcapPyException(self.err)

    filter = property(get_filter, set_filter)

    @property
    def selectable_fd(self):
        return pcap_get_selectable_fd(self._p)

    @property
    def can_set_rfmon(self):
        return pcap_can_set_rfmon(self._p) == 1

    def get_direction(self):
        return self._direction

    def set_direction(self, value):
        if value not in [PCAP_D_INOUT, PCAP_D_IN, PCAP_D_OUT]:
            raise ValueError(
                'Must be either PCAP_D_INOUT (%s), PCAP_D_IN (%s), or PCAP_D_OUT (%s)' %
                (
                    PCAP_D_INOUT,
                    PCAP_D_IN,
                    PCAP_D_OUT
                )
            )
        if pcap_setdirection(self._p, value) < 0:
            raise PcapPyException(self.err)
        self._direction = value

    direction = property(get_direction, set_direction)

    @property
    def fileno(self):
        return pcap_fileno(self._p)


class PcapPyOffline(PcapPyAlive):

    _is_base = False

    def __init__(self, file_):
        super(PcapPyOffline, self).__init__()
        errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
        if isinstance(file_, file):
            self._p = pcap_fopen_offline(PyFile_AsFile(file_), c_char_p((addressof(errbuf))))
        else:
            self._p = pcap_open_offline(file_, c_char_p((addressof(errbuf))))
        self.filename = file_
        if not self._p:
            raise PcapPyException(errbuf.raw)

    @property
    def file(self):
        f = pcap_file(self._p)
        return PyFile_FromFile(f, self.filename, "rb", None)


class PcapPyLive(PcapPyAlive):

    _is_base = False

    def __init__(self, device, snaplen=64, promisc=1, to_ms=1000, activate=True, **kwargs):
        super(PcapPyLive, self).__init__()
        self._device = device
        self._promisc = promisc
        self._timeout = to_ms
        self._activate = activate
        self._rfmon = kwargs.get('rfmon', 0)
        self._buffer_size = kwargs.get('buffer_size', None)
        errbuf = create_string_buffer(PCAP_ERRBUF_SIZE)
        if self._activate and not self._rfmon and self._buffer_size is None:
            self._p = pcap_open_live(device, snaplen, promisc, to_ms, c_char_p((addressof(errbuf))))
            if not to_ms and (sys.platform.startswith('linux') or sys.platform == 'darwin'):                
                from fcntl import ioctl
                try:
                    ioctl(self.fileno, BIOCIMMEDIATE, pack("I", 1))
                except IOError:
                    pass
            if not self._p:
                raise PcapPyException(errbuf.raw)
        else:
            self._p = pcap_create(device, c_char_p((addressof(errbuf))))
            if not self._p:
                raise PcapPyException(errbuf.raw)
            self.snaplen = snaplen
            self.promisc = self._promisc
            self.timeout = self._timeout
            if self._rfmon:
                self.rfmon = self._rfmon
            if self._buffer_size is not None:
                self.buffer_size = self._buffer_size
            if self._activate:
                self.activate()

    def sendpacket(self, data):
        r = pcap_sendpacket(self._p, data, len(data))
        if r == -1:
            raise PcapPyException(self.err)
        return r

    def inject(self, data):
        r = pcap_inject(self._p, data, len(data))
        if r == -1:
            raise PcapPyException(self.err)
        return r

    def activate(self):
        if pcap_activate(self._p) < 0:
            raise PcapPyException(self.err)

    @property
    def device(self):
        return self._device

    def get_rfmon(self):
        return self._rfmon

    def set_rfmon(self, value):
        if pcap_set_rfmon(self._p, value) < 0:
            raise PcapPyException(self.err)
        self._rfmon = value

    rfmon = property(get_rfmon, set_rfmon)

    def get_timeout(self):
        return self._timeout

    def set_timeout(self, value):
        if pcap_set_timeout(self._p, value) < 0:
            raise PcapPyException(self.err)
        self._timeout = value

    timeout = property(get_timeout, set_timeout)

    def get_promisc(self):
        return self._promisc

    def set_promisc(self, value):
        if pcap_set_promisc(self._p, value) < 0:
            raise PcapPyException(self.err)
        self._promisc = value

    promisc = property(get_promisc, set_promisc)

    def get_buffer_size(self):
        return self._buffer_size

    def set_buffer_size(self, value):
        if pcap_set_buffer_size(self._p, value) < 0:
            raise PcapPyException(self.err)
        self._buffer_size = value

    buffer_size = property(get_buffer_size, set_buffer_size)
