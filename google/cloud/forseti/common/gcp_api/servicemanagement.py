# Copyright 2017 The Forseti Security Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Wrapper for Service Management API client."""
from builtins import object
from googleapiclient import errors
from httplib2 import HttpLib2Error

from google.cloud.forseti.common.gcp_api import _base_repository
from google.cloud.forseti.common.gcp_api import api_helpers
from google.cloud.forseti.common.gcp_api import errors as api_errors
from google.cloud.forseti.common.gcp_api import repository_mixins
from google.cloud.forseti.common.util import logger

LOGGER = logger.get_logger(__name__)
API_NAME = 'servicemanagement'


class ServiceManagementRepositoryClient(_base_repository.BaseRepositoryClient):
    """Service Management API Respository."""

    def __init__(self,
                 quota_max_calls=None,
                 quota_period=100.0,
                 use_rate_limiter=True,
                 cache_discovery=False,
                 cache=None):
        """Constructor.

        Args:
            quota_max_calls (int): Allowed requests per <quota_period> for the
                API.
            quota_period (float): The time period to track requests over.
            use_rate_limiter (bool): Set to false to disable the use of a rate
                limiter for this service.
            cache_discovery (bool): When set to true, googleapiclient will cache
                HTTP requests to API discovery endpoints.
            cache (googleapiclient.discovery_cache.base.Cache): instance of a
                class that can cache API discovery documents. If None,
                googleapiclient will attempt to choose a default.
        """
        if not quota_max_calls:
            use_rate_limiter = False

        self._services = None

        super(ServiceManagementRepositoryClient, self).__init__(
            API_NAME, versions=['v1'],
            quota_max_calls=quota_max_calls,
            quota_period=quota_period,
            use_rate_limiter=use_rate_limiter,
            cache_discovery=cache_discovery,
            cache=cache)

    # Turn off docstrings for properties.
    # pylint: disable=missing-return-doc, missing-return-type-doc
    @property
    def services(self):
        """Returns a _ServiceManagementServicesRepository instance."""
        if not self._services:
            self._services = self._init_repository(
                _ServiceManagementServicesRepository)
        return self._services
    # pylint: enable=missing-return-doc, missing-return-type-doc


class _ServiceManagementServicesRepository(
        repository_mixins.GetIamPolicyQueryMixin,
        repository_mixins.ListQueryMixin,
        _base_repository.GCPRepository):
    """Implementation of Service Management Services repository.

    NOTE: unlike the list() API used for other GCP resources, the
    services.list() API does not accept a singular 'resource'. Instead, two
    optional arguments allow specification of either the producer (parent)
    project (which results in a list of its child services), or the consumer
    project (which results in a list of services enabled on that project).
    If neither is specified, services.list() returns *all* visible services
    (where visibility is based on the provided credentials).
    """

    def __init__(self, **kwargs):
        """Constructor.

        Args:
            **kwargs (dict): The args to pass into GCPRepository.__init__()
        """
        super(_ServiceManagementServicesRepository, self).__init__(
            component='services', max_results_field='pageSize',
            key_field='serviceName', **kwargs)

    @staticmethod
    def get_formatted_project_name(project_id):
        """Returns a formatted project_id string, required for some api args.

        Args:
            project_id (str): The project id to query, either just the
                id or the id prefixed with 'projects/'.

        Returns:
            str: The formatted project id.
        """
        if not project_id.startswith('project:'):
            project_id = 'project:{}'.format(project_id)
        return project_id

    @staticmethod
    def get_formatted_service_name(service_name):
        """Returns a formatted service_name string, required for some api args.

        Args:
            service_name (str): The name of the service to query.

        Returns:
            str: The formatted service name.
        """
        if not service_name.startswith('services/'):
            service_name = 'services/{}'.format(service_name)
        return service_name

    def get_config(self, resource, config_id=None, view=None, verb='getConfig'):
        """Gets the Service Configuration associated with a Service.

        Args:
            resource (str): Name of the service
            config_id (str): The ID of the Service Configuration to fetch
            view (ConfigView): Specifies which portion of the Service
                Configuration should be returned.
                https://cloud.google.com/service-infrastructure/docs/service-management/reference/rest/v1/ConfigView
            verb (str): The method to call on the API.

        Returns:
            dict: Response from the API (of type Service)
                https://cloud.google.com/service-infrastructure/docs/service-management/reference/rest/v1/services.configs#Service
        """
        arguments = {
            self._get_key_field: resource,
        }

        if config_id:
            arguments['configId'] = config_id
        if view:
            arguments['view'] = view

        return self.execute_query(
            verb=verb,
            verb_arguments=arguments,
        )


class ServiceManagementClient(object):
    """Service Management Client."""

    # Maximum number of results to fetch per page for paged API calls
    DEFAULT_MAX_RESULTS = 100

    def __init__(self, global_configs, **kwargs):
        """Initialize.

        Args:
            global_configs (dict): Global configurations.
            **kwargs (dict): The kwargs.
        """
        max_calls, quota_period = api_helpers.get_ratelimiter_config(
            global_configs, API_NAME)

        cache_discovery = global_configs[
            'cache_discovery'] if 'cache_discovery' in global_configs else False

        self.repository = ServiceManagementRepositoryClient(
            quota_max_calls=max_calls,
            quota_period=quota_period,
            use_rate_limiter=kwargs.get('use_rate_limiter', True),
            cache_discovery=cache_discovery,
            cache=global_configs.get('cache'))

    def get_all_apis(self):
        """Gets all APIs that can be enabled (based on caller's permissions).

        Returns:
            list: A list of ManagedService resource dicts.
            https://cloud.google.com/service-management/reference/rest/v1/services#ManagedService

            {
              "serviceName": string,
              "producerProjectId": string,
            }
        Raises:
            ApiExecutionError: ApiExecutionError is raised if the call to the
                GCP API fails.
        """
        try:
            paged_results = self.repository.services.list(
                max_results=self.DEFAULT_MAX_RESULTS)
            flattened_results = api_helpers.flatten_list_results(paged_results,
                                                                 'services')
        except (errors.HttpError, HttpLib2Error) as e:
            api_exception = api_errors.ApiExecutionError('', e)
            LOGGER.exception(api_exception)
            raise api_exception

        LOGGER.debug('Getting all visible APIs, flattened_results = %s',
                     flattened_results)
        return flattened_results

    def get_produced_apis(self, project_id):
        """Gets the APIs produced by a project.

        Args:
            project_id (str): The project id for a GCP project.

        Returns:
            list: A list of ManagedService resource dicts.
            https://cloud.google.com/service-management/reference/rest/v1/services#ManagedService

            {
              "serviceName": string,
              "producerProjectId": string,
            }
        Raises:
            ApiExecutionError: ApiExecutionError is raised if the call to the
                GCP API fails.
        """
        try:
            paged_results = self.repository.services.list(
                producerProjectId=project_id,
                max_results=self.DEFAULT_MAX_RESULTS)
            flattened_results = api_helpers.flatten_list_results(paged_results,
                                                                 'services')
        except (errors.HttpError, HttpLib2Error) as e:
            api_exception = api_errors.ApiExecutionError(
                'name', e, 'project_id', project_id)
            LOGGER.exception(api_exception)
            raise api_exception

        LOGGER.debug('Getting the APIs produced by a project, project_id = %s, '
                     'flattened_results = %s', project_id, flattened_results)
        return flattened_results

    def get_enabled_apis(self, project_id):
        """Gets the enabled APIs for a project.

        Args:
            project_id (str): The project id for a GCP project.

        Returns:
            list: A list of ManagedService resource dicts.
            https://cloud.google.com/service-management/reference/rest/v1/services#ManagedService

            {
              "serviceName": string,
              "producerProjectId": string,
            }
        Raises:
            ApiExecutionError: ApiExecutionError is raised if the call to the
                GCP API fails.
        """
        # The consumerId arg must be formatted as 'project:<project_id>'
        formatted_project_id = self.repository.services.\
            get_formatted_project_name(project_id)
        try:
            paged_results = self.repository.services.list(
                consumerId=formatted_project_id,
                max_results=self.DEFAULT_MAX_RESULTS)
            flattened_results = api_helpers.flatten_list_results(paged_results,
                                                                 'services')
        except (errors.HttpError, HttpLib2Error) as e:
            api_exception = api_errors.ApiExecutionError(
                'name', e, 'project_id', project_id)
            LOGGER.exception(api_exception)
            raise api_exception

        LOGGER.debug('Getting the enabled APIs for a project, project_id = %s, '
                     'flattened_results = %s', project_id, flattened_results)
        return flattened_results

    def get_api_iam_policy(self, service_name):
        """Gets the IAM policy associated with a service.

        NOTE: This does *not* include IAM policy inherited from a service's
        producer project. (I.e. project-level IAM Policy may grant service-level
        permissions that do not appear in a service's IAM Policy.)

        Args:
            service_name (str): The service name to query.

        Returns:
            dict: A single Policy resource dict.
            https://cloud.google.com/service-infrastructure/docs/service-management/reference/rest/v1/Policy

            {
              "version": string,
              "bindings": list(Binding),
              "auditConfigs": list(AuditConfig),
              "etag": string,
            }

        Raises:
            ApiExecutionError: ApiExecutionError is raised if the call to the
                GCP API fails.
        """
        # The service_name arg must be formatted as 'services/<service_name>'
        name = self.repository.services.get_formatted_service_name(service_name)
        try:
            result = self.repository.services.get_iam_policy(name)
        except (errors.HttpError, HttpLib2Error) as e:
            api_exception = api_errors.ApiExecutionError(
                'serviceIamPolicy', e, 'serviceName', service_name)
            LOGGER.exception(api_exception)
            raise api_exception

        LOGGER.debug('Getting IAM Policy for a service, service_name = %s, '
                     'result = %s', service_name, result)
        return result

    def get_full_api_configuration(self, service_name):
        """Gets the full Service Configuration associated with a service.

        Args:
            service_name (str): The service name to query.

        Returns:
            dict: A single Service resource dict.
            https://cloud.google.com/service-infrastructure/docs/service-management/reference/rest/v1/services.configs#Service

        Raises:
            ApiExecutionError: ApiExecutionError is raised if the call to the
                GCP API fails.
        """
        try:
            result = self.repository.services.get_config(service_name)
        except (errors.HttpError, HttpLib2Error) as e:
            api_exception = api_errors.ApiExecutionError(
                'serviceConfig', e, 'serviceName', service_name)
            LOGGER.exception(api_exception)
            raise api_exception

        LOGGER.debug('Getting Service Config for a service, service_name = %s, '
                     'result = %s', service_name, result)

        return result
