import argparse
import contextlib
import os
import time
import unittest
import unittest.mock

import sfs.cli as cli
import sfs.core as core
import sfs.events as events
import sfs.exceptions as exceptions
import sfs.helper as sfs_helper
import sfs.log_utils as log
import sfs.tests.helper as test_helper

import sfs.ops.ops_collection as ops_collection
import sfs.ops.ops_main as ops_main
import sfs.ops.ops_query as ops_query


# Settings


# Register sub command parsers
events.invoke_subscribers(events.events['CLI_REGISTRY'], cli.command_subparsers, parents=[])

# Disable logging
log.logger.disabled = True


# Helpers


def cli_exec(cmd, ignore_errors=False):
    """Mocks CLI output logger and returns the collected output"""
    with unittest.mock.patch('sfs.log_utils.cli_output') as cli_output:
        with cli.cli_manager(cmd, exit_on_error=False, raise_error=not ignore_errors) as args:
            events.invoke_subscribers(events.command_key(args.command), args)
        return cli_output.call_args_list


@contextlib.contextmanager
def change_cwd(path):
    """Provides a context with a specified working directory"""
    old = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old)


def prepare_args(*args, **kwargs):
    """Arranges all positional and keyword arguments to match the structure of unittest.mock._CallList"""
    return args, kwargs


def prepare_validation_error(message):
    """Constructs a validation error message"""
    return "{} {}".format(cli.error_messages['VALIDATION'], message)


def prepare_internal_error_error(message):
    """Constructs an internal error message"""
    return "{} {}".format(cli.error_messages['INTERNAL'], message)


class CLIManagerTests(unittest.TestCase):

    def test_cli_manager(self):
        test_cmd = [ops_main.commands['SFS_INIT']]
        with unittest.mock.patch('sfs.log_utils.cli_output') as cli_output:
            with cli.cli_manager(test_cmd, exit_on_error=False) as args:
                pass
            self.assertEqual(argparse.Namespace(command=ops_main.commands['SFS_INIT'], verbose=False), args)
            self.assertIsNone(cli_output.call_args)

    def test_cli_manager_validation_error(self):
        test_cmd = [ops_main.commands['SFS_INIT']]
        exception_message = 'test message'
        with unittest.mock.patch('sfs.log_utils.cli_output') as cli_output:
            with cli.cli_manager(test_cmd, exit_on_error=False) as args:
                raise exceptions.CLIValidationException(exception_message)
            self.assertEqual(prepare_args(prepare_validation_error(exception_message)), cli_output.call_args)

    def test_cli_manager_internal_error(self):
        test_cmd = [ops_main.commands['SFS_INIT']]
        exception_message = 'test message'
        with unittest.mock.patch('sfs.log_utils.cli_output') as cli_output:
            with cli.cli_manager(test_cmd, exit_on_error=False) as args:
                raise exceptions.SFSException(exception_message)
            self.assertEqual(prepare_args(prepare_internal_error_error(exception_message)), cli_output.call_args)

    def test_cli_manager_unknown_error(self):
        test_cmd = [ops_main.commands['SFS_INIT']]
        exception_message = 'test message'
        with unittest.mock.patch('sfs.log_utils.cli_output') as cli_output:
            with cli.cli_manager(test_cmd, exit_on_error=False) as args:
                raise Exception(exception_message)
            self.assertEqual(prepare_args(cli.error_messages['UNKNOWN']), cli_output.call_args)


class MainOpsCLITests(test_helper.TestCaseWithFS):

    def test_init(self):
        with unittest.mock.patch('sfs.core.SFS.init_sfs') as init_sfs:
            path = self.TESTS_BASE

            with change_cwd(path):
                # Initializes SFS in an empty directory
                output = cli_exec([ops_main.commands['SFS_INIT']])
                self.assertEqual([], output)
                self.assertEqual(1, len(init_sfs.call_args_list))
                self.assertEqual(prepare_args(path), init_sfs.call_args)

                # Add a file to the target directory
                os.mkdir(os.path.join(path, 'test'))

                # Cannot initialize SFS in a non-empty directory
                output = cli_exec([ops_main.commands['SFS_INIT']], ignore_errors=True)
                self.assertEqual([
                    prepare_args(prepare_validation_error(ops_main.messages['INIT']['ERROR']['NON_EMPTY_DIR']))
                ], output)
                self.assertEqual(1, len(init_sfs.call_args_list))

    def test_init_inside_sfs(self):
        # Initialize an SFS
        path = self.TESTS_BASE
        core.SFS.init_sfs(path)

        # Cannot initialize a nested SFS
        with unittest.mock.patch('sfs.core.SFS.init_sfs') as init_sfs:
            path = os.path.join(path, 'test')
            os.mkdir(path)
            with change_cwd(path):
                output = cli_exec([ops_main.commands['SFS_INIT']], ignore_errors=True)
                self.assertEqual([
                    prepare_args(prepare_validation_error(ops_main.messages['INIT']['ERROR']['NESTED_SFS']))
                ], output)
                self.assertEqual(0, len(init_sfs.call_args_list))
                self.assertIsNone(init_sfs.call_args)

    def test_is_sfs(self):
        # Initialize an SFS
        sfs_root = os.path.join(self.TESTS_BASE, 'sfs_root')
        os.mkdir(sfs_root)
        core.SFS.init_sfs(sfs_root)
        sfs = core.SFS.get_by_path(sfs_root)

        with unittest.mock.patch('sfs.core.SFS.get_by_path') as get_by_path:
            get_by_path.return_value = sfs
            for path in [sfs_root, os.path.join(sfs_root, 'nested')]:
                os.makedirs(path, exist_ok=True)

                # Works with path argument
                output = cli_exec([ops_main.commands['IS_SFS'], '--path', path])
                self.assertEqual([
                    prepare_args("{}{}".format(ops_main.messages['IS_SFS']['OUTPUT']['YES'], sfs_root))
                ], output)
                self.assertEqual(prepare_args(path), get_by_path.call_args)

                # Uses current directory if path not specified
                with change_cwd(path):
                    output = cli_exec([ops_main.commands['IS_SFS']])
                    self.assertEqual([
                        prepare_args("{}{}".format(ops_main.messages['IS_SFS']['OUTPUT']['YES'], sfs_root))
                    ], output)
                    self.assertEqual(prepare_args(path), get_by_path.call_args)

            # Called correct no of time
            self.assertEqual(4, len(get_by_path.call_args_list))

            # Output is negative for paths outside SFS
            get_by_path.return_value = None
            for path in [self.TESTS_BASE, os.path.join(self.TESTS_BASE, 'nested')]:
                output = cli_exec([ops_main.commands['IS_SFS'], '--path', path])
                self.assertEqual([
                    prepare_args(ops_main.messages['IS_SFS']['OUTPUT']['NO'])
                ], output)
                self.assertEqual(prepare_args(path), get_by_path.call_args)

            # Called correct no of time
            self.assertEqual(6, len(get_by_path.call_args_list))


class CollectionOpsCLITests(test_helper.TestCaseWithFS):

    def __init__(self, *args, **kwargs):
        super(CollectionOpsCLITests, self).__init__(*args, **kwargs)
        self.col_tree = {
            'files': ['file_a', 'file_b'],
            'links': ['link_a'],
            'dirs': {
                'dir_a': {
                    'files': ['file_aa']
                }
            }
        }
        self.sfs_root = os.path.join(self.TESTS_BASE, 'sfs_root')
        self.col_root = os.path.join(self.TESTS_BASE, 'col')
        self.col_name = 'col'

    def setUp(self):
        super(CollectionOpsCLITests, self).setUp()

        # Create collection and SFS nodes
        os.mkdir(self.sfs_root)
        os.mkdir(self.col_root)
        self.create_fs_tree(self.col_tree, base=self.col_root)

        # Change working directory to sfs root and save old value
        self.old_cwd = os.getcwd()
        os.chdir(self.sfs_root)
        core.SFS.init_sfs(self.sfs_root)
        self.sfs = core.SFS.get_by_path(self.sfs_root)

    def tearDown(self):
        super(CollectionOpsCLITests, self).tearDown()

        # Restore working directory
        os.chdir(self.old_cwd)

    def _test_not_sfs_dir(self, cmd, msg, *mocked_modules):
        not_sfs_dir = self.TESTS_BASE
        for mocked_module in mocked_modules:
            with unittest.mock.patch(mocked_module) as mocked:
                with change_cwd(not_sfs_dir):
                    output = cli_exec(cmd, ignore_errors=True)
                    self.assertEqual([
                        prepare_args(prepare_validation_error(msg))
                    ], output)
                    self.assertEqual(0, len(mocked.call_args_list))

    def test_add_collection(self):
        dummy_sfs_updates = core.SfsUpdates(added=4, deleted=2, updated=3)
        col_name = 'test_col'
        with unittest.mock.patch('sfs.core.SFS.add_collection') as add_collection:
            add_collection.return_value = dummy_sfs_updates

            # Outputs success message to terminal
            output = cli_exec([ops_collection.commands['ADD_COL'], self.col_root, '--name', col_name])
            self.assertEqual([
                prepare_args("{} {}".format(ops_collection.messages['ADD_COL']['OUTPUT'], 4))
            ], output)

            # Receives correct arguments
            self.assertEqual(1, len(add_collection.call_args_list))
            self.assertEqual(prepare_args(col_name, self.col_root), add_collection.call_args)

            # Collection name defaults to collection root name
            cli_exec([ops_collection.commands['ADD_COL'], self.col_root])
            self.assertEqual(2, len(add_collection.call_args_list))
            self.assertEqual(prepare_args(self.col_name, self.col_root), add_collection.call_args)

    def test_add_collection_validations(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['ADD_COL'], self.col_root],
            ops_collection.messages['ADD_COL']['ERROR']['NOT_IN_SFS'],
            'sfs.core.SFS.add_collection'
        )

        # Path should be an existing directory
        not_dir = os.path.join(self.TESTS_BASE, 'not_dir')
        with unittest.mock.patch('sfs.core.SFS.add_collection') as add_collection:
            output = cli_exec([ops_collection.commands['ADD_COL'], not_dir], ignore_errors=True)
            self.assertEqual([
                prepare_args(prepare_validation_error(ops_collection.messages['ADD_COL']['ERROR']['INVALID_PATH']))
            ], output)
            self.assertEqual(0, len(add_collection.call_args_list))

        # Cannot add path within an SFS
        within_sfs = os.path.join(self.sfs_root, 'nested_dir')
        os.mkdir(within_sfs)
        with unittest.mock.patch('sfs.core.SFS.add_collection') as add_collection:
            output = cli_exec([ops_collection.commands['ADD_COL'], within_sfs], ignore_errors=True)
            self.assertEqual([
                prepare_args(prepare_validation_error(ops_collection.messages['ADD_COL']['ERROR']['NESTED_SFS']))
            ], output)
            self.assertEqual(0, len(add_collection.call_args_list))

        # Actually add a collection
        col_name = 'test_col'
        self.sfs.add_collection(col_name, self.col_root)

        # Cannot add path within a collection
        within_col = os.path.join(self.col_root, 'nested_dir')
        os.mkdir(within_col)
        with unittest.mock.patch('sfs.core.SFS.add_collection') as add_collection:
            output = cli_exec([ops_collection.commands['ADD_COL'], within_col], ignore_errors=True)
            self.assertEqual([
                prepare_args(prepare_validation_error(ops_collection.messages['ADD_COL']['ERROR']['NESTED_COL']))
            ], output)
            self.assertEqual(0, len(add_collection.call_args_list))

        # Cannot add collection with a duplicate name
        new_col = os.path.join(self.TESTS_BASE, 'col2')
        os.mkdir(new_col)
        with unittest.mock.patch('sfs.core.SFS.add_collection') as add_collection:
            output = cli_exec([ops_collection.commands['ADD_COL'], new_col, '--name', col_name], ignore_errors=True)
            self.assertEqual([
                prepare_args(prepare_validation_error(ops_collection.messages['ADD_COL']['ERROR']['NAME_EXISTS']))
            ], output)
            self.assertEqual(0, len(add_collection.call_args_list))

    def test_is_collection(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['IS_COL'], self.col_root],
            ops_collection.messages['IS_COL']['ERROR']['NOT_IN_SFS'],
            'sfs.core.SFS.get_collection_by_path'
        )

        col_name = 'test_col'
        sfs = core.SFS.get_by_path(self.sfs_root)
        sfs.add_collection(col_name, self.col_root)
        col = sfs.get_collection_by_name(col_name)

        with unittest.mock.patch('sfs.core.SFS.get_collection_by_path') as get_collection_by_path:

            # Outputs positively for paths within a collection
            get_collection_by_path.return_value = col
            for path in [self.col_root, os.path.join(self.col_root, 'nested')]:
                output = cli_exec([ops_collection.commands['IS_COL'], path])
                self.assertEqual([
                    prepare_args("{} {}".format(ops_collection.messages['IS_COL']['OUTPUT']['YES'], self.col_root))
                ], output)
                self.assertEqual(prepare_args(path), get_collection_by_path.call_args)

            # Called correct no of times
            self.assertEqual(2, len(get_collection_by_path.call_args_list))

            # Outputs negatively for paths outside collections
            get_collection_by_path.return_value = None
            for path in [self.TESTS_BASE, os.path.join(self.TESTS_BASE, 'nested')]:
                output = cli_exec([ops_collection.commands['IS_COL'], path])
                self.assertEqual([
                    prepare_args(ops_collection.messages['IS_COL']['OUTPUT']['NO'])
                ], output)
                self.assertEqual(prepare_args(path), get_collection_by_path.call_args)

            # Called correct no of times
            self.assertEqual(4, len(get_collection_by_path.call_args_list))

    def test_list_cols(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['LIST_COLS']],
            ops_collection.messages['LIST_COLS']['ERROR']['NOT_IN_SFS'],
            'sfs.core.SFS.get_all_collections'
        )

        # Outputs negatively when there are no collections
        with unittest.mock.patch('sfs.core.SFS.get_all_collections') as get_all_collections:
            get_all_collections.return_value = {}
            output = cli_exec([ops_collection.commands['LIST_COLS']])
            self.assertEqual([
                prepare_args(ops_collection.messages['LIST_COLS']['OUTPUT']['NOT_AVAILABLE'])
            ], output)
            self.assertEqual(prepare_args(), get_all_collections.call_args)
            self.assertEqual(1, len(get_all_collections.call_args_list))

        # Add 2 collections
        col1_name = 'col1'
        col1_root = self.col_root
        col2_name = 'col2'
        col2_root = os.path.join(self.TESTS_BASE, 'col2')
        os.mkdir(col2_root)
        sfs = core.SFS.get_by_path(self.sfs_root)
        sfs.add_collection(col1_name, col1_root)
        sfs.add_collection(col2_name, col2_root)
        sfs_list = sfs.get_all_collections()

        with unittest.mock.patch('sfs.core.SFS.get_all_collections') as get_all_collections:
            get_all_collections.return_value = sfs_list
            output = cli_exec([ops_collection.commands['LIST_COLS']])
            self.assertEqual([
                prepare_args("{}{}".format(ops_collection.messages['LIST_COLS']['OUTPUT']['COUNT'], len(sfs_list))),
                prepare_args('{}"{}"\t{}"{}"'.format(
                    ops_collection.messages['LIST_COLS']['OUTPUT']['COL_NAME'], col1_name,
                    ops_collection.messages['LIST_COLS']['OUTPUT']['COL_ROOT'], col1_root
                )),
                prepare_args('{}"{}"\t{}"{}"'.format(
                    ops_collection.messages['LIST_COLS']['OUTPUT']['COL_NAME'], col2_name,
                    ops_collection.messages['LIST_COLS']['OUTPUT']['COL_ROOT'], col2_root
                ))
            ], output)
            self.assertEqual(prepare_args(), get_all_collections.call_args)
            self.assertEqual(1, len(get_all_collections.call_args_list))

    def test_sync_col(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['SYNC_COL'], self.col_name],
            ops_collection.messages['SYNC_COL']['ERROR']['NOT_IN_SFS'],
            'sfs.core.Collection.update',
            'sfs.core.SFS.del_orphans'
        )

        # Add a collection
        sfs = core.SFS.get_by_path(self.sfs_root)
        sfs.add_collection(self.col_name, self.col_root)
        updates_in_sync = core.SfsUpdates(added=3, updated=5, deleted=0)
        updates_in_del = core.SfsUpdates(added=0, updated=0, deleted=4)

        with unittest.mock.patch('sfs.core.Collection.update') as update_collection:
            with unittest.mock.patch('sfs.core.SFS.del_orphans') as del_orphans:
                update_collection.return_value = updates_in_sync
                del_orphans.return_value = updates_in_del

                # Outputs number of links updated
                output = cli_exec([ops_collection.commands['SYNC_COL'], self.col_name])
                self.assertEqual([
                    prepare_args(
                        '{}{}'.format(ops_collection.messages['SYNC_COL']['OUTPUT']['ADDED'], updates_in_sync.added)
                    ),
                    prepare_args(
                        '{}{}'.format(ops_collection.messages['SYNC_COL']['OUTPUT']['UPDATED'], updates_in_sync.updated)
                    ),
                    prepare_args(
                        '{}{}'.format(ops_collection.messages['SYNC_COL']['OUTPUT']['DELETED'], updates_in_del.deleted)
                    )
                ], output)
                self.assertEqual([prepare_args()], update_collection.call_args_list)
                self.assertEqual([prepare_args(col_root=self.col_root)], del_orphans.call_args_list)

                # Reports negatively for unknown collection name
                output = cli_exec([ops_collection.commands['SYNC_COL'], 'unknown_col'], ignore_errors=True)
                self.assertEqual([
                    prepare_args(prepare_validation_error(
                        ops_collection.messages['SYNC_COL']['ERROR']['NOT_A_COL_NAME']
                    ))
                ], output)

    def test_del_col(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['DEL_COL'], self.col_name],
            ops_collection.messages['DEL_COL']['ERROR']['NOT_IN_SFS'],
            'sfs.core.SFS.del_collection'
        )

        # Add a collection
        sfs = core.SFS.get_by_path(self.sfs_root)
        sfs.add_collection(self.col_name, self.col_root)
        updates_in_del = core.SfsUpdates(added=0, updated=0, deleted=3)

        with unittest.mock.patch('sfs.core.SFS.del_collection') as del_collection:
            with unittest.mock.patch('sfs.core.SFS.del_orphans') as del_orphans:
                del_collection.return_value = None
                del_orphans.return_value = updates_in_del

                # Expect a blank output
                output = cli_exec([ops_collection.commands['DEL_COL'], self.col_name])
                self.assertEqual([
                    prepare_args('{}{}'.format(
                        ops_collection.messages['DEL_ORPHANS']['OUTPUT'], updates_in_del.deleted
                    ))
                ], output)
                self.assertEqual([prepare_args(self.col_name)], del_collection.call_args_list)

                # Reports negatively for unknown collection name
                output = cli_exec([ops_collection.commands['DEL_COL'], 'unknown_col'], ignore_errors=True)
                self.assertEqual([
                    prepare_args(prepare_validation_error(
                        ops_collection.messages['DEL_COL']['ERROR']['NOT_A_COL_NAME']
                    ))
                ], output)

    def test_del_orphans(self):
        # Must be inside an SFS
        self._test_not_sfs_dir(
            [ops_collection.commands['DEL_ORPHANS']],
            ops_collection.messages['DEL_ORPHANS']['ERROR']['NOT_IN_SFS'],
            'sfs.core.SFS.del_orphans'
        )

        updates_in_del = core.SfsUpdates(added=0, updated=0, deleted=8)

        # Reports no of links deleted
        with unittest.mock.patch('sfs.core.SFS.del_orphans') as del_orphans:
            del_orphans.return_value = updates_in_del
            output = cli_exec([ops_collection.commands['DEL_ORPHANS']])
            self.assertEqual([
                prepare_args('{}{}'.format(ops_collection.messages['DEL_ORPHANS']['OUTPUT'], updates_in_del.deleted))
            ], output)
            self.assertEqual([prepare_args()], del_orphans.call_args_list)


class QueryOpsCLITests(test_helper.TestCaseWithFS):

    def __init__(self, *args, **kwargs):
        super(QueryOpsCLITests, self).__init__(*args, **kwargs)
        self.sfs_root = os.path.join(self.TESTS_BASE, 'sfs_root')
        self.col_root = os.path.join(self.TESTS_BASE, 'col')
        self.col_name = 'col'
        self.col_path = os.path.join(self.col_root, 'file')
        self.link_path = os.path.join(self.sfs_root, self.col_name, 'file')

    def setUp(self):
        super(QueryOpsCLITests, self).setUp()

        # Create collection and SFS nodes
        os.mkdir(self.sfs_root)
        os.mkdir(self.col_root)
        test_helper.dummy_file(self.col_path, 100)

        core.SFS.init_sfs(self.sfs_root)
        self.sfs = core.SFS.get_by_path(self.sfs_root)
        self.sfs.add_collection(self.col_name, self.col_root)
        self.col = self.sfs.get_collection_by_name(self.col_name)

    def test_query_link(self):
        # Reports link info
        output = cli_exec([ops_query.commands['QUERY'], '--path', self.link_path])
        self.assertEqual([
            prepare_args("{}{}".format(ops_query.messages['QUERY']['OUTPUT']['LINK']['COL_NAME'], self.col_name)),
            prepare_args("{}{}".format(ops_query.messages['QUERY']['OUTPUT']['LINK']['COL_PATH'], self.col_path)),
            prepare_args("{}{}".format(
                ops_query.messages['QUERY']['OUTPUT']['LINK']['CTIME'],
                time.ctime(os.stat(self.col_path).st_ctime)
            )),
            prepare_args("{}{}".format(
                ops_query.messages['QUERY']['OUTPUT']['LINK']['SIZE'],
                sfs_helper.get_readable_size(100)
            )),
        ], output)

    def test_query_directory(self):
        dir_path = self.sfs_root
        dir_stats = ops_query.DirectoryStats()
        dir_stats.size = 1
        dir_stats.ctime = 2
        dir_stats.active_links = 3
        dir_stats.orphan_links = 4
        dir_stats.foreign_links = 5
        dir_stats.files = 6
        dir_stats.sub_directories = 7

        # Reports directory info. If path not specified current directory is used
        with unittest.mock.patch('sfs.ops.ops_query.compute_directory_stats') as compute_directory_stats:
            compute_directory_stats.return_value = dir_stats
            with change_cwd(dir_path):
                for output in [
                    cli_exec([ops_query.commands['QUERY'], '--path', dir_path]),
                    cli_exec([ops_query.commands['QUERY']]),
                ]:
                    self.assertEqual([
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['SIZE'],
                            sfs_helper.get_readable_size(dir_stats.size)
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['CTIME'], time.ctime(dir_stats.ctime)
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['ACTIVE_LINKS'], dir_stats.active_links
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['FOREIGN_LINKS'], dir_stats.foreign_links
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['ORPHAN_LINKS'], dir_stats.orphan_links
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['FILES'], dir_stats.files
                        )),
                        prepare_args("{}{}".format(
                            ops_query.messages['QUERY']['OUTPUT']['DIR']['SUB_DIRECTORIES'], dir_stats.sub_directories
                        ))
                    ], output)
                    self.assertIsNotNone(compute_directory_stats.call_args)
                    self.assertEqual(2, len(compute_directory_stats.call_args[0]))
                    self.assertIsInstance(compute_directory_stats.call_args[0][0], core.SFS)
                    self.assertEqual(compute_directory_stats.call_args[0][1], dir_path)
            self.assertEqual(2, len(compute_directory_stats.call_args_list))

    def test_query_link_validations(self):
        # Must be inside an SFS
        not_sfs = self.TESTS_BASE
        output = cli_exec([ops_query.commands['QUERY'], '--path', not_sfs], ignore_errors=True)
        self.assertEqual([
            prepare_args(prepare_validation_error(ops_query.messages['QUERY']['ERROR']['NOT_IN_SFS']))
        ], output)

        # Path must be link or directory
        file_path = os.path.join(self.sfs_root, 'test_file')
        test_helper.dummy_file(file_path)
        output = cli_exec([ops_query.commands['QUERY'], '--path', file_path], ignore_errors=True)
        self.assertEqual([
            prepare_args(prepare_validation_error(ops_query.messages['QUERY']['ERROR']['NOT_LINK_OR_DIR']))
        ], output)

        # Link must belong to a collection
        foreign_link = os.path.join(self.sfs_root, 'foreign_link')
        test_helper.dummy_link(foreign_link)
        output = cli_exec([ops_query.commands['QUERY'], '--path', foreign_link], ignore_errors=True)
        self.assertEqual([
            prepare_args(prepare_validation_error(ops_query.messages['QUERY']['ERROR']['COLLECTION_NOT_FOUND']))
        ], output)

        # Stats must be available
        stats_path = os.path.join(self.col.stats_base, 'file')
        os.unlink(stats_path)
        output = cli_exec([ops_query.commands['QUERY'], '--path', self.link_path], ignore_errors=True)
        self.assertEqual([
            prepare_args(prepare_validation_error(ops_query.messages['QUERY']['ERROR']['STATS_NOT_FOUND']))
        ], output)