from django import forms
from constance import config
from django.conf import settings
from gravity.models import GravitySensor, GravityLogPoint, GravityLog, TiltConfiguration, IspindelConfiguration, IspindelGravityCalibrationPoint, TiltBridge, TiltGravityCalibrationPoint
from app.models import BrewPiDevice
from django.forms import ModelForm
from django.core.validators import RegexValidator
from django.core.exceptions import ObjectDoesNotExist
import sys

try:
    # Bluetooth support isn't always available as it requires additional work to install. Going to carve this out to
    # pop up an error message.
    if sys.platform != "darwin":
        import aioblescan
    bluetooth_loaded = True
except ImportError:
    bluetooth_loaded = False

###################################################################################################################
# Generic (Manual) Forms
###################################################################################################################


# Manual sensors don't have special configuration.
class ManualForm(ModelForm):
    class Meta:
        model = GravitySensor
        fields = ['name', 'temp_format',]

    def __init__(self, *args, **kwargs):
        super(ManualForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"

    def clean(self):  # TODO - Determine if this should be clean_color instead of clean
        # The override of "clean" only exists to allow us to be able to validate that there isn't an existing gravity
        # sensor with the same name as the one the user is attempting to add.
        cleaned_data = self.cleaned_data

        if cleaned_data.get("name"):
            try:
                GravitySensor.objects.get(name__iexact=cleaned_data['name'])
                raise forms.ValidationError("A gravity sensor with the name {} ".format(cleaned_data['name']) +
                                            "already exists. Please choose another name.")
            except ObjectDoesNotExist:
                pass

        return cleaned_data


# Manual sensors don't have special configuration.
class ManualPointForm(ModelForm):
    class Meta:
        model = GravityLogPoint
        fields = ['gravity', 'temp', 'temp_format', 'temp_is_estimate', 'extra_data']

    def __init__(self, *args, **kwargs):
        super(ManualPointForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"


class GravityLogCreateForm(forms.Form):
    log_name = forms.CharField(max_length=255, min_length=1, required=True, )
    device = forms.ChoiceField(required=True)

    @staticmethod
    def get_device_choices():
        choices = []
        # We specifically do not want to include any devices that are assigned to temperature controllers as these are
        # being controlled by the linked temperature controller
        available_devices = GravitySensor.objects.filter(assigned_brewpi_device=None)
        for this_device in available_devices:
            device_tuple = (this_device.id, this_device.name)
            choices.append(device_tuple)
        return choices

    def __init__(self, *args, **kwargs):
        super(GravityLogCreateForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"
        self.fields['device'] = forms.ChoiceField(required=True, choices=self.get_device_choices(),
                                                  widget=forms.Select(attrs={'class': 'form-control',
                                                                             'data-toggle': 'select'}))

    def clean(self):
        cleaned_data = self.cleaned_data

        if cleaned_data.get("log_name"):
            # Due to the fact that the beer name is used in file paths, we need to validate it to prevent "injection"
            # type attacks
            log_name = cleaned_data.get("log_name")
            if GravityLog.name_is_valid(log_name):
                cleaned_data['log_name'] = log_name
            else:
                raise forms.ValidationError("Log name must only consist of letters, numbers, dashes, spaces, " +
                                            "and underscores")
        else:
            raise forms.ValidationError("Log name must be specified")

        try:
            linked_device = GravitySensor.objects.get(id=cleaned_data.get('device'))
            cleaned_data['device'] = linked_device
        except:
            raise forms.ValidationError("Invalid device ID specified!")

        if linked_device.assigned_brewpi_device is not None:
            raise forms.ValidationError("This device is managed by a temperature controller - To create a log, go to " +
                                        "the controller's dashboard and start a new beer log there")

        return cleaned_data


class SensorAttachForm(forms.Form):
    sensor = forms.ChoiceField(required=True)
    temp_controller = forms.ChoiceField(required=True)

    @staticmethod
    def get_sensor_choices():
        choices = []
        available_sensors = GravitySensor.objects.filter(assigned_brewpi_device=None)
        for this_device in available_sensors:
            device_tuple = (this_device.id, this_device.name)
            choices.append(device_tuple)
        return choices

    @staticmethod
    def get_controller_choices():
        choices = []
        available_devices = BrewPiDevice.objects.filter(gravity_sensor=None)
        for this_device in available_devices:
            device_tuple = (this_device.id, this_device.device_name)
            choices.append(device_tuple)
        return choices

    def __init__(self, *args, **kwargs):
        super(SensorAttachForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"
        self.fields['sensor'] = forms.ChoiceField(required=True, choices=self.get_sensor_choices(),
                                                  widget=forms.Select(attrs={'class': 'form-control',
                                                                             'data-toggle': 'select'}))
        self.fields['temp_controller'] = forms.ChoiceField(required=True, choices=self.get_controller_choices(),
                                                           widget=forms.Select(attrs={'class': 'form-control',
                                                                                      'data-toggle': 'select'}))

    def clean(self):
        cleaned_data = self.cleaned_data

        try:
            sensor = GravitySensor.objects.get(id=cleaned_data.get('sensor'), assigned_brewpi_device=None)
            cleaned_data['sensor'] = sensor
        except:
            raise forms.ValidationError("Invalid gravity sensor specified!")

        try:
            temp_controller = BrewPiDevice.objects.get(id=cleaned_data.get('temp_controller'), gravity_sensor=None)
            cleaned_data['temp_controller'] = temp_controller
        except:
            raise forms.ValidationError("Invalid temperature controller specified!")

        return cleaned_data


class TiltBridgeForm(forms.ModelForm):
    class Meta:
        model = TiltBridge
        fields = ['name', 'mdns_id', ]


class TiltCreateForm(forms.Form):
    key_validator = RegexValidator(r"[0-9A-Za-z_-]+", "Key can only consist of 0-9, A-Z, a-z, dashes, and underscores.")

    name = forms.CharField(max_length=255, min_length=1, required=True, )
    temp_format = forms.ChoiceField(required=True, choices=GravitySensor.TEMP_FORMAT_CHOICES)
    color = forms.ChoiceField(required=True, choices=TiltConfiguration.COLOR_CHOICES)

    # With the addition of TiltBridge support, we now need to allow the user to choose a connection type for Tilt
    # hydrometers (either Bluetooth or TiltBridge)
    connection_type = forms.ChoiceField(required=True, choices=TiltConfiguration.CONNECTION_CHOICES)

    # If the user chooses to connect via TiltBridge, allow them to select an existing TiltBridge device. If no devices
    # have been set up, the template will prompt the user to create one.
    tiltbridge = forms.ChoiceField(required=False, help_text="Select a TiltBridge for this Tilt to connect through")

    @staticmethod
    def get_tiltbridge_choices():
        choices = []
        available_tiltbridges = TiltBridge.objects.all()
        for this_tiltbridge in available_tiltbridges:
            device_tuple = (this_tiltbridge.mdns_id, this_tiltbridge.name)
            choices.append(device_tuple)
        return choices

    def clean_color(self):
        if self.cleaned_data.get("color"):
            # Although the color uniqueness check is enforced on the database insert, I want to check it here as well
            try:
                # If an object already exists with the color that was specified, error out.
                obj_with_color = TiltConfiguration.objects.get(color=self.cleaned_data['color'])
            except:
                obj_with_color = None

            if obj_with_color is not None:
                raise forms.ValidationError("There is already a Tilt sensor configured with "
                                            "the color {}".format(self.cleaned_data['color']))
        else:
            raise forms.ValidationError("Tilt sensors require a color to be specified")

        return self.cleaned_data['color']

    def clean_name(self):
        # Enforce uniqueness for sensor name
        if self.cleaned_data.get("name"):
            try:
                # Check to make sure that the name of the gravity sensor is unique
                GravitySensor.objects.get(name__iexact=self.cleaned_data['name'])
                raise forms.ValidationError("A gravity sensor with the name {} ".format(self.cleaned_data['name']) +
                                            "already exists. Please choose another name.")
            except ObjectDoesNotExist:
                pass
        return self.cleaned_data['name']

    def clean_connection_type(self):
        if self.cleaned_data.get('connection_type'):
            if self.cleaned_data.get('connection_type') == TiltConfiguration.CONNECTION_BLUETOOTH and not bluetooth_loaded:
                raise forms.ValidationError('Bluetooth packages for python have not been installed. Tilt Hydrometers '
                                            'cannot be connected via Bluetooth.')
        return self.cleaned_data['connection_type']


    def __init__(self, *args, **kwargs):
        super(TiltCreateForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"
        self.fields['tiltbridge'] = forms.ChoiceField(required=False, choices=self.get_tiltbridge_choices(),
                                                      widget=forms.Select(attrs={'class': 'form-control',
                                                                                 'data-toggle': 'select'}))


class TiltCoefficientForm(forms.Form):
    # Allow for inputting the coefficients/constant term of the gravity equation (if known)
    # a = forms.DecimalField(required=False, help_text="The third degree coefficient of the gravity equation")
    b = forms.DecimalField(required=False, help_text="The second degree coefficient of the gravity equation")
    c = forms.DecimalField(required=False, help_text="The first degree coefficient of the gravity equation")
    d = forms.DecimalField(required=False, help_text="The constant term of the gravity equation")

    def __init__(self, *args, **kwargs):
        super(TiltCoefficientForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"


class TiltGravityCalibrationPointForm(forms.ModelForm):
    class Meta:
        model = TiltGravityCalibrationPoint
        fields = ['actual_gravity', 'tilt_measured_gravity', 'sensor']


class IspindelCreateForm(forms.Form):
    name = forms.CharField(max_length=255, min_length=1, required=True, )
    temp_format = forms.ChoiceField(required=True, choices=GravitySensor.TEMP_FORMAT_CHOICES)
    name_on_device = forms.CharField(max_length=64, min_length=1, required=True,
                                     widget=forms.TextInput(attrs={'placeholder': 'iSpindel000'}))

    def clean_name_on_device(self):
        if self.cleaned_data.get("name_on_device"):
            # Although the name_on_device uniqueness check is enforced on the database insert, I want to check it here as well
            try:
                # If an object already exists with the name_on_device that was specified, error out.
                obj_with_name = IspindelConfiguration.objects.get(name_on_device=self.cleaned_data['name_on_device'])
            except:
                obj_with_name = None

            if obj_with_name is not None:
                raise forms.ValidationError("There is already an iSpindel sensor configured with "
                                            "the name {}".format(self.cleaned_data['name_on_device']))
        else:
            raise forms.ValidationError("iSpindel sensors require a name on device to be specified")

        return self.cleaned_data['name_on_device']

    def clean_name(self):
        # Enforce uniqueness for sensor name
        if self.cleaned_data.get("name"):
            try:
                # Check to make sure that the name of the gravity sensor is unique
                GravitySensor.objects.get(name__iexact=self.cleaned_data['name'])
                raise forms.ValidationError("A gravity sensor with the name {} ".format(self.cleaned_data['name']) +
                                            "already exists. Please choose another name.")
            except ObjectDoesNotExist:
                pass
        return self.cleaned_data['name']

    def __init__(self, *args, **kwargs):
        super(IspindelCreateForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"


class IspindelCoefficientForm(forms.Form):
    # Allow for inputting the coefficients/constant term of the gravity equation (if known)
    a = forms.DecimalField(required=False, help_text="The third degree coefficient of the gravity equation")
    b = forms.DecimalField(required=False, help_text="The second degree coefficient of the gravity equation")
    c = forms.DecimalField(required=False, help_text="The first degree coefficient of the gravity equation")
    d = forms.DecimalField(required=False, help_text="The constant term of the gravity equation")

    def __init__(self, *args, **kwargs):
        super(IspindelCoefficientForm, self).__init__(*args, **kwargs)
        for this_field in self.fields:
            self.fields[this_field].widget.attrs['class'] = "form-control"


class IspindelCalibrationPointForm(forms.ModelForm):
    class Meta:
        model=IspindelGravityCalibrationPoint
        fields=['angle', 'gravity', 'sensor']
