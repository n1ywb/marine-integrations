"""
@package mi.dataset.driver.mflm.phsen.test.test_driver
@file marine-integrations/mi/dataset/driver/mflm/phsen/driver.py
@author Emily Hahn
@brief Test cases for mflm_phsen driver

USAGE:
 Make tests verbose and provide stdout
   * From the IDK
       $ bin/dsa/test_driver
       $ bin/dsa/test_driver -i [-t testname]
       $ bin/dsa/test_driver -q [-t testname]
"""

__author__ = 'Emily Hahn'
__license__ = 'Apache 2.0'

import unittest
import os

from nose.plugins.attrib import attr
from mock import Mock

from mi.core.log import get_logger ; log = get_logger()
from mi.core.instrument.instrument_driver import DriverEvent
from mi.idk.exceptions import SampleTimeout

from mi.idk.dataset.unit_test import DataSetTestCase
from mi.idk.dataset.unit_test import DataSetIntegrationTestCase
from mi.idk.dataset.unit_test import DataSetQualificationTestCase

from mi.dataset.dataset_driver import DataSourceConfigKey, DataSetDriverConfigKeys
from mi.dataset.dataset_driver import DriverParameter, DriverStateKey

from mi.dataset.driver.mflm.phsen.driver import MflmPHSENDataSetDriver
from mi.dataset.parser.phsen import PhsenParserDataParticle

from pyon.agent.agent import ResourceAgentState
from interface.objects import ResourceAgentErrorEvent
from interface.objects import ResourceAgentConnectionLostErrorEvent

# Fill in driver details
DataSetTestCase.initialize(
    driver_module='mi.dataset.driver.mflm.phsen.driver',
    driver_class='MflmPHSENDataSetDriver',
    agent_resource_id = '123xyz',
    agent_name = 'Agent007',
    agent_packet_config = MflmPHSENDataSetDriver.stream_config(),
    startup_config = {
        DataSourceConfigKey.HARVESTER:
        {
            DataSetDriverConfigKeys.DIRECTORY: '/tmp/dsatest',
            DataSetDriverConfigKeys.STORAGE_DIRECTORY: '/tmp/stored_dsatest',
            DataSetDriverConfigKeys.PATTERN: 'node59p1.dat',
            DataSetDriverConfigKeys.FREQUENCY: 1,
        },
        DataSourceConfigKey.PARSER: {}
    }
)

SAMPLE_STREAM = 'phsen_parsed'

###############################################################################
#                            INTEGRATION TESTS                                #
# Device specific integration tests are for                                   #
# testing device specific capabilities                                        #
###############################################################################
@attr('INT', group='mi')
class IntegrationTest(DataSetIntegrationTestCase):

    def clean_file(self):
        # remove just the file we are using
        driver_config = self._driver_config()['startup_config']
        log.debug('startup config %s', driver_config)
        fullfile = os.path.join(driver_config['harvester']['directory'],
                            driver_config['harvester']['pattern'])
        if os.path.exists(fullfile):
            os.remove(fullfile)

    def test_get(self):
        """
        Test that we can get data from files.  Verify that the driver
        sampling can be started and stopped
        """
        self.clean_file()

        # Start sampling and watch for an exception
        self.driver.start_sampling()

        self.clear_async_data()
        self.create_sample_data("node59p1_step1.dat", "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_1.txt.result.yml',
                         count=1, timeout=10)

        # there is only one file we read from, this example 'appends' data to
        # the end of the node59p1.dat file, and the data from the new append
        # is returned (not including the original data from _step1)
        self.clear_async_data()
        self.create_sample_data("node59p1_step2.dat", "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_2.txt.result.yml',
                         count=1, timeout=10)

        # now 'appends' the rest of the data and just check if we get the right number
        self.clear_async_data()
        self.create_sample_data("node59p1_step4.dat", "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, count=2, timeout=10)

        self.driver.stop_sampling()
        # Reset the driver with no memento
        self.memento = None
        self.driver = MflmPHSENDataSetDriver(
            self._driver_config()['startup_config'],
            self.memento,
            self.data_callback,
            self.state_callback,
            self.exception_callback)
        self.driver.start_sampling()

        self.clear_async_data()
        self.create_sample_data("node59p1_step1.dat", "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, count=1, timeout=10)

    def test_harvester_new_file_exception(self):
        """
        Test an exception raised after the driver is started during
        the file read.  Should call the exception callback.
        """
        self.clean_file()

        # create the file so that it is unreadable
        self.create_sample_data("node59p1_step1.dat", "node59p1.dat", mode=000)

        # Start sampling and watch for an exception
        self.driver.start_sampling()

        self.assert_exception(ValueError)

        # At this point the harvester thread is dead.  The agent
        # exception handle should handle this case.

    def test_stop_resume(self):
        """
        Test the ability to stop and restart the process
        """
        self.clean_file()
        self.create_sample_data("node59p1_step1.dat", "node59p1.dat")
        driver_config = self._driver_config()['startup_config']
        fullfile = os.path.join(driver_config['harvester']['directory'],
                            driver_config['harvester']['pattern'])
        mod_time = os.path.getmtime(fullfile)

        # Create and store the new driver state
        self.memento = {DriverStateKey.FILE_SIZE: 911,
                        DriverStateKey.FILE_CHECKSUM: '8b7cf73895eded0198b3f3621f962abc',
                        DriverStateKey.FILE_MOD_DATE: mod_time,
                        DriverStateKey.PARSER_STATE: {'in_process_data': [],
                                                     'unprocessed_data':[[0, 172]],
                                                     'timestamp': 3583699199.0}
                        }

        self.driver = MflmPHSENDataSetDriver(
            self._driver_config()['startup_config'],
            self.memento,
            self.data_callback,
            self.state_callback,
            self.exception_callback)

        # create some data to parse
        self.clear_async_data()
        self.create_sample_data("node59p1_step2.dat", "node59p1.dat")

        self.driver.start_sampling()

        # verify data is produced
        self.assert_data(PhsenParserDataParticle, 'test_data_2.txt.result.yml',
                         count=1, timeout=10)

    def test_sequences(self):
        """
        Test new sequence flags are set correctly
        """
        self.clean_file()

        self.driver.start_sampling()

        self.clear_async_data()

        # step 2 contains 2 blocks, start with this and get both since we used them
        # separately in other tests (no new sequences)
        self.clear_async_data()
        self.create_sample_data("node59p1_step2.dat", "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_1-2.txt.result.yml',
                         count=2, timeout=10)

        # This file has had a section of data replaced with 0s, this should start a new
        # sequence for the data following the missing data
        self.clear_async_data()
        self.create_sample_data('node59p1_step3.dat', "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_3.txt.result.yml',
                         count=1, timeout=10)

        # Now fill in the zeroed section from step3, this should just return the new
        # data with a new sequence flag
        self.clear_async_data()
        self.create_sample_data('node59p1_step4.dat', "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_4.txt.result.yml',
                         count=1, timeout=10)

        # start over now, using step 4, make sure sequence flags just account for
        # missing data in file (there are some sections of bad data that don't
        # match in headers
        self.driver.stop_sampling()
        # Reset the driver with no memento
        self.memento = None
        self.driver = MflmPHSENDataSetDriver(
            self._driver_config()['startup_config'],
            self.memento,
            self.data_callback,
            self.state_callback,
            self.exception_callback)
        self.driver.start_sampling()

        self.clear_async_data()
        self.create_sample_data('node59p1_step4.dat', "node59p1.dat")
        self.assert_data(PhsenParserDataParticle, 'test_data_1-4.txt.result.yml',
                         count=4, timeout=10)

###############################################################################
#                            QUALIFICATION TESTS                              #
# Device specific qualification tests are for                                 #
# testing device specific capabilities                                        #
###############################################################################
@attr('QUAL', group='mi')
class QualificationTest(DataSetQualificationTestCase):
    def setUp(self):
        super(QualificationTest, self).setUp()
        
    def clean_file(self):
        # remove just the file we are using
        driver_config = self._driver_config()['startup_config']
        log.debug('startup config %s', driver_config)
        fullfile = os.path.join(driver_config['harvester']['directory'],
                            driver_config['harvester']['pattern'])
        if os.path.exists(fullfile):
            os.remove(fullfile)

    def test_harvester_new_file_exception(self):
        """
        Test an exception raised after the driver is started during
        the file read.

        exception callback called.
        """
        self.clean_file()
        # need to put data in the file, not just make an empty file for this to work
        self.create_sample_data('node59p1_step4.dat', "node59p1.dat", mode=000)

        self.assert_initialize(final_state=ResourceAgentState.COMMAND)

        self.event_subscribers.clear_events()
        self.assert_resource_command(DriverEvent.START_AUTOSAMPLE)
        self.assert_state_change(ResourceAgentState.LOST_CONNECTION, 90)
        self.assert_event_received(ResourceAgentConnectionLostErrorEvent, 10)

        self.clean_file()
        self.create_sample_data('node59p1_step4.dat', "node59p1.dat")

        # Should automatically retry connect and transition to streaming
        self.assert_state_change(ResourceAgentState.STREAMING, 90)

    def test_publish_path(self):
        """
        Setup an agent/driver/harvester/parser and verify that data is
        published out the agent
        """
        self.clean_file()

        self.create_sample_data('node59p1_step1.dat', "node59p1.dat")

        self.assert_initialize()

        try:
            # Verify we get one sample
            result = self.data_subscribers.get_samples(SAMPLE_STREAM, 1)
            log.info("RESULT: %s", result)

            # Verify values
            self.assert_data_values(result, 'test_data_1.txt.result.yml')
        except Exception as e:
            log.error("Exception trapped: %s", e)
            self.fail("Sample timeout.")

    def test_large_import(self):
        """
        Test importing a large number of samples from the file at once
        """
        self.create_sample_data('node59p1_orig.dat', "node59p1.dat")
        self.assert_initialize()

        result = self.get_samples(SAMPLE_STREAM,24,60)

    def test_stop_start(self):
        """
        Test the agents ability to start data flowing, stop, then restart
        at the correct spot.
        """
        log.info("CONFIG: %s", self._agent_config())
        self.create_sample_data('node59p1_step2.dat', "node59p1.dat")

        self.assert_initialize(final_state=ResourceAgentState.COMMAND)

        # Slow down processing to 1 per second to give us time to stop
        self.dataset_agent_client.set_resource({DriverParameter.RECORDS_PER_SECOND: 1})
        self.assert_start_sampling()

        # Verify we get one sample
        try:
            # Read the first file and verify the data
            result = self.get_samples(SAMPLE_STREAM, 2)
            log.debug("RESULT: %s", result)

            # Verify values
            self.assert_data_values(result, 'test_data_1-2.txt.result.yml')
            self.assert_sample_queue_size(SAMPLE_STREAM, 0)

            self.create_sample_data('node59p1_step4.dat', "node59p1.dat")
            # Now read the first record of the second file then stop
            result1 = self.get_samples(SAMPLE_STREAM, 1)
            log.debug("RESULT 1: %s", result1)
            self.assert_stop_sampling()
            self.assert_sample_queue_size(SAMPLE_STREAM, 0)

            # Restart sampling and ensure we get the last record of the file
            self.assert_start_sampling()
            result2 = self.get_samples(SAMPLE_STREAM, 1)
            log.debug("RESULT 2: %s", result2)
            result = result1
            result.extend(result2)
            log.debug("RESULT: %s", result)
            self.assert_data_values(result, 'test_data_3-4.txt.result.yml')

            self.assert_sample_queue_size(SAMPLE_STREAM, 0)
        except SampleTimeout as e:
            log.error("Exception trapped: %s", e, exc_info=True)
            self.fail("Sample timeout.")

    def test_parser_exception(self):
        """
        Test an exception is raised after the driver is started during
        record parsing.
        """
        self.clean_file()
        # file contains invalid sample values
        self.create_sample_data('node59p1_step4.dat', "node59p1.dat")

        self.assert_initialize()

        self.event_subscribers.clear_events()
        result = self.get_samples(SAMPLE_STREAM, 4)
        self.assert_sample_queue_size(SAMPLE_STREAM, 0)

        # Verify an event was raised and we are in our retry state
        self.assert_event_received(ResourceAgentErrorEvent, 10)
        self.assert_state_change(ResourceAgentState.STREAMING, 10)

