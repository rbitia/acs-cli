"""Tests for `acs demo` subcommand."""

import pytest

class TestDemo():
    slow = pytest.mark.skipif(
        not pytest.config.getoption("--runslow"),
        reason="need --runslow option to run"
    )

    @slow
    def test_lbweb_slow(self, demo, service):
        """Tests the creation of a cluster and the lbweb demo. This version of the test will delete any pre-existing service.
        """
        if service.exists():
            service.log.debug("The test ACS cluster already exists, deleting")
            service.delete(True)

        demo.args = {'<command>': 'lbweb',
                     "--remove": False}
        try:
            result = demo.lbweb()
            assert("Application deployed" in result)
        except RuntimeWarning as e:
            demo.log.warning("The application was already installed so the test was not as thorough as it could have been")

        
        # remove the appliction
        demo.args["--remove"] = True
        result = demo.lbweb()
        assert("Application removed" in result)

        
    def test_lbweb(self, demo, service):
        """Tests the creation of the lbweb demo. This version of the test will fail if the test cluster dows not already exist.

        """
        assert(service.exists())

        demo.args = {'<command>': 'lbweb',
                     "--remove": False}
        try:
            result = demo.lbweb()
            assert("Application deployed" in result)
        except RuntimeWarning as e:
            demo.log.warning("The application was already installed so the test was not as thorough as it could have been")
        
        # remove the appliction
        demo.args["--remove"] = True
        result = demo.lbweb()
        assert("Application removed" in result)