# Copyright 2012 NTT Data. All Rights Reserved.
# Copyright 2012 Yahoo! Inc. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import contextlib
import functools
import os

import mock
from oslo.config import cfg

from nova import exception
from nova.openstack.common import processutils
from nova import test
from nova import utils
from nova.virt import images
from nova.virt.libvirt import utils as libvirt_utils

CONF = cfg.CONF


class LibvirtUtilsTestCase(test.NoDBTestCase):
    def test_get_disk_type(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
blah BLAH: bb
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        disk_type = libvirt_utils.get_disk_type(path)
        self.assertEqual(disk_type, 'raw')

    def test_logical_volume_size(self):
        executes = []

        def fake_execute(*cmd, **kwargs):
            executes.append(cmd)
            return 123456789, None

        expected_commands = [('blockdev', '--getsize64', '/dev/foo')]
        self.stubs.Set(utils, 'execute', fake_execute)
        size = libvirt_utils.logical_volume_size('/dev/foo')
        self.assertEqual(expected_commands, executes)
        self.assertEqual(size, 123456789)

    def test_lvm_clear(self):
        def fake_lvm_size(path):
            return lvm_size

        def fake_execute(*cmd, **kwargs):
            executes.append(cmd)

        self.stubs.Set(libvirt_utils, 'logical_volume_size', fake_lvm_size)
        self.stubs.Set(utils, 'execute', fake_execute)

        # Test the correct dd commands are run for various sizes
        lvm_size = 1
        executes = []
        expected_commands = [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v1',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v1')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1024
        executes = []
        expected_commands = [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v2',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v2')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1025
        executes = []
        expected_commands = [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v3',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v3',
                               'seek=1024', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v3')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1048576
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v4',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v4')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1048577
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v5',
                              'seek=0', 'count=1', 'oflag=direct')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v5',
                               'seek=1048576', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v5')
        self.assertEqual(expected_commands, executes)

        lvm_size = 1234567
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v6',
                              'seek=0', 'count=1', 'oflag=direct')]
        expected_commands += [('dd', 'bs=1024', 'if=/dev/zero', 'of=/dev/v6',
                               'seek=1024', 'count=181', 'conv=fdatasync')]
        expected_commands += [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/v6',
                               'seek=1233920', 'count=647', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/v6')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear_size limits the size
        lvm_size = 10485761
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v7',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v7')
        self.assertEqual(expected_commands, executes)

        CONF.set_override('volume_clear_size', '2', 'libvirt')
        lvm_size = 1048576
        executes = []
        expected_commands = [('dd', 'bs=1048576', 'if=/dev/zero', 'of=/dev/v9',
                              'seek=0', 'count=1', 'oflag=direct')]
        libvirt_utils.clear_logical_volume('/dev/v9')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=shred
        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '0', 'libvirt')
        lvm_size = 1048576
        executes = []
        expected_commands = [('shred', '-n3', '-s1048576', '/dev/va')]
        libvirt_utils.clear_logical_volume('/dev/va')
        self.assertEqual(expected_commands, executes)

        CONF.set_override('volume_clear', 'shred', 'libvirt')
        CONF.set_override('volume_clear_size', '1', 'libvirt')
        lvm_size = 10485761
        executes = []
        expected_commands = [('shred', '-n3', '-s1048576', '/dev/vb')]
        libvirt_utils.clear_logical_volume('/dev/vb')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=none does nothing
        CONF.set_override('volume_clear', 'none', 'libvirt')
        executes = []
        expected_commands = []
        libvirt_utils.clear_logical_volume('/dev/vc')
        self.assertEqual(expected_commands, executes)

        # Test volume_clear=invalid falls back to the default 'zero'
        CONF.set_override('volume_clear', 'invalid', 'libvirt')
        lvm_size = 1
        executes = []
        expected_commands = [('dd', 'bs=1', 'if=/dev/zero', 'of=/dev/vd',
                              'seek=0', 'count=1', 'conv=fdatasync')]
        libvirt_utils.clear_logical_volume('/dev/vd')
        self.assertEqual(expected_commands, executes)

    def test_list_rbd_volumes(self):
        conf = '/etc/ceph/fake_ceph.conf'
        pool = 'fake_pool'
        user = 'user'
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        self.mox.StubOutWithMock(libvirt_utils.utils,
                                 'execute')
        libvirt_utils.utils.execute('rbd', '-p', pool, 'ls', '--id',
                                    user,
                                    '--conf', conf).AndReturn(("Out", "Error"))
        self.mox.ReplayAll()

        libvirt_utils.list_rbd_volumes(pool)

        self.mox.VerifyAll()

    def test_remove_rbd_volumes(self):
        conf = '/etc/ceph/fake_ceph.conf'
        pool = 'fake_pool'
        user = 'user'
        names = ['volume1', 'volume2', 'volume3']
        self.flags(images_rbd_ceph_conf=conf, group='libvirt')
        self.flags(rbd_user=user, group='libvirt')
        self.mox.StubOutWithMock(libvirt_utils.utils, 'execute')
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume1',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume2',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        libvirt_utils.utils.execute('rbd', '-p', pool, 'rm', 'volume3',
                                    '--id', user, '--conf', conf, attempts=3,
                                    run_as_root=True)
        self.mox.ReplayAll()

        libvirt_utils.remove_rbd_volumes(pool, *names)

        self.mox.VerifyAll()

    @mock.patch('nova.utils.execute')
    def test_copy_image_local_cp(self, mock_execute):
        libvirt_utils.copy_image('src', 'dest')
        mock_execute.assert_called_once_with('cp', 'src', 'dest')

    _rsync_call = functools.partial(mock.call,
                                    'rsync', '--sparse', '--compress')

    @mock.patch('nova.utils.execute')
    def test_copy_image_rsync(self, mock_execute):
        libvirt_utils.copy_image('src', 'dest', host='host')

        mock_execute.assert_has_calls([
            self._rsync_call('--dry-run', 'src', 'host:dest'),
            self._rsync_call('src', 'host:dest'),
        ])
        self.assertEqual(2, mock_execute.call_count)

    def test_fail_remove_all_logical_volumes(self):

        def fake_execute(*args, **kwargs):
            if 'vol2' in args:
                raise processutils.ProcessExecutionError('Error')

        with contextlib.nested(
             mock.patch.object(libvirt_utils, 'clear_logical_volume'),
             mock.patch.object(libvirt_utils, 'execute',
                  side_effect=fake_execute)) as (mock_clear, mock_execute):
            self.assertRaises(exception.VolumesNotRemoved,
                              libvirt_utils.remove_logical_volumes,
                              ['vol1', 'vol2', 'vol3'])
            self.assertEqual(3, mock_execute.call_count)

    @mock.patch('nova.utils.execute')
    def test_copy_image_scp(self, mock_execute):
        mock_execute.side_effect = [
            processutils.ProcessExecutionError,
            mock.DEFAULT,
        ]

        libvirt_utils.copy_image('src', 'dest', host='host')

        mock_execute.assert_has_calls([
            self._rsync_call('--dry-run', 'src', 'host:dest'),
            mock.call('scp', 'src', 'host:dest'),
        ])
        self.assertEqual(2, mock_execute.call_count)


class ImageUtilsTestCase(test.NoDBTestCase):
    def test_disk_type(self):
        # Seems like lvm detection
        # if its in /dev ??
        for p in ['/dev/b', '/dev/blah/blah']:
            d_type = libvirt_utils.get_disk_type(p)
            self.assertEqual('lvm', d_type)

        # Try rbd detection
        d_type = libvirt_utils.get_disk_type('rbd:pool/instance')
        self.assertEqual('rbd', d_type)

        # Try the other types
        template_output = """image: %(path)s
file format: %(format)s
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
"""
        path = '/myhome/disk.config'
        for f in ['raw', 'qcow2']:
            output = template_output % ({
                'format': f,
                'path': path,
            })
            self.mox.StubOutWithMock(os.path, 'exists')
            self.mox.StubOutWithMock(utils, 'execute')
            os.path.exists(path).AndReturn(True)
            utils.execute('env', 'LC_ALL=C', 'LANG=C',
                          'qemu-img', 'info', path).AndReturn((output, ''))
            self.mox.ReplayAll()
            d_type = libvirt_utils.get_disk_type(path)
            self.assertEqual(f, d_type)
            self.mox.UnsetStubs()

    def test_disk_backing(self):
        path = '/myhome/disk.config'
        template_output = """image: %(path)s
file format: raw
virtual size: 2K (2048 bytes)
cluster_size: 65536
disk size: 96K
"""
        output = template_output % ({
            'path': path,
        })
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((output, ''))
        self.mox.ReplayAll()
        d_backing = libvirt_utils.get_disk_backing_file(path)
        self.assertIsNone(d_backing)

    def test_disk_size(self):
        path = '/myhome/disk.config'
        template_output = """image: %(path)s
file format: raw
virtual size: %(v_size)s (%(vsize_b)s bytes)
cluster_size: 65536
disk size: 96K
"""
        for i in range(0, 128):
            bytes = i * 65336
            kbytes = bytes / 1024
            mbytes = kbytes / 1024
            output = template_output % ({
                'v_size': "%sM" % (mbytes),
                'vsize_b': i,
                'path': path,
            })
            self.mox.StubOutWithMock(os.path, 'exists')
            self.mox.StubOutWithMock(utils, 'execute')
            os.path.exists(path).AndReturn(True)
            utils.execute('env', 'LC_ALL=C', 'LANG=C',
                          'qemu-img', 'info', path).AndReturn((output, ''))
            self.mox.ReplayAll()
            d_size = libvirt_utils.get_disk_size(path)
            self.assertEqual(i, d_size)
            self.mox.UnsetStubs()
            output = template_output % ({
                'v_size': "%sK" % (kbytes),
                'vsize_b': i,
                'path': path,
            })
            self.mox.StubOutWithMock(os.path, 'exists')
            self.mox.StubOutWithMock(utils, 'execute')
            os.path.exists(path).AndReturn(True)
            utils.execute('env', 'LC_ALL=C', 'LANG=C',
                          'qemu-img', 'info', path).AndReturn((output, ''))
            self.mox.ReplayAll()
            d_size = libvirt_utils.get_disk_size(path)
            self.assertEqual(i, d_size)
            self.mox.UnsetStubs()

    def test_qemu_info_canon(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
blah BLAH: bb
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        image_info = images.qemu_img_info(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)

    def test_qemu_info_canon2(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: QCOW2
virtual size: 67108844
cluster_size: 65536
disk size: 963434
backing file: /var/lib/nova/a328c7998805951a_2
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        image_info = images.qemu_img_info(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('qcow2', image_info.file_format)
        self.assertEqual(67108844, image_info.virtual_size)
        self.assertEqual(963434, image_info.disk_size)
        self.assertEqual(65536, image_info.cluster_size)
        self.assertEqual('/var/lib/nova/a328c7998805951a_2',
                         image_info.backing_file)

    def test_qemu_backing_file_actual(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
cluster_size: 65536
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1     d9a9784a500742a7bb95627bb3aace38      0 2012-08-20 10:52:46 00:00:00.000
backing file: /var/lib/nova/a328c7998805951a_2 (actual path: /b/3a988059e51a_2)
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        image_info = images.qemu_img_info(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(1, len(image_info.snapshots))
        self.assertEqual('/b/3a988059e51a_2',
                         image_info.backing_file)

    def test_qemu_info_convert(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
3        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
4        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
junk stuff: bbb
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        image_info = images.qemu_img_info(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)

    def test_qemu_info_snaps(self):
        path = "disk.config"
        example_output = """image: disk.config
file format: raw
virtual size: 64M (67108864 bytes)
disk size: 96K
Snapshot list:
ID        TAG                 VM SIZE                DATE       VM CLOCK
1        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
3        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
4        d9a9784a500742a7bb95627bb3aace38    0 2012-08-20 10:52:46 00:00:00.000
"""
        self.mox.StubOutWithMock(os.path, 'exists')
        self.mox.StubOutWithMock(utils, 'execute')
        os.path.exists(path).AndReturn(True)
        utils.execute('env', 'LC_ALL=C', 'LANG=C',
                      'qemu-img', 'info', path).AndReturn((example_output, ''))
        self.mox.ReplayAll()
        image_info = images.qemu_img_info(path)
        self.assertEqual('disk.config', image_info.image)
        self.assertEqual('raw', image_info.file_format)
        self.assertEqual(67108864, image_info.virtual_size)
        self.assertEqual(98304, image_info.disk_size)
        self.assertEqual(3, len(image_info.snapshots))
