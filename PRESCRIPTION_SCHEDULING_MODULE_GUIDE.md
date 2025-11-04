# Prescription Scheduling Module - Complete Setup Guide

## 🎯 Overview
The Prescription Scheduling Module provides a comprehensive solution for managing prescription status, dispatch to procurement departments, and tracking changes throughout the prescription lifecycle.

## 📋 Module Information
- **Module Name**: Prescription Scheduling
- **URL**: `/prescription-scheduling/`
- **Icon**: 📋
- **Description**: Manage prescription status, dispatch to procurement departments, and track changes throughout the prescription lifecycle

## 👥 Roles and Permissions

### **Roles with Access**
1. **Super Admin (IT Department)** - Full access
2. **Admin (Administrative GM / Management)** - Full access
3. **Doctor** - Create and manage prescriptions
4. **Scheduling Staff** - Manage scheduling and dispatch
5. **Prescription Scheduler** - Manage prescription scheduling and dispatch
6. **Prescription Admin** - Full administrative access
7. **Procurement Staff** - View and update prescription status
8. **IP Pharmacy Staff** - Handle pharmacy-related prescriptions

### **Custom Permissions Created**
- `send_final_prescription` - Can send final prescriptions to procurement
- `view_prescription_details` - Can view detailed prescription information
- `update_prescription_status` - Can update prescription status
- `view_change_log` - Can view prescription change logs
- `manage_prescription_dispatch` - Can manage prescription dispatch
- `bulk_prescription_operations` - Can perform bulk prescription operations

## 🚀 Features Available

### **1. Draft Prescription Management**
- View all draft prescriptions
- Filter by date range
- Send final prescriptions to procurement departments
- View prescription details and items

### **2. Scheduled Prescription Tracking**
- Monitor prescriptions sent to procurement
- Track which department is handling each prescription
- View dispatch status and timestamps

### **3. Dispatched Prescription Monitoring**
- View all completed prescriptions
- Track final dispatch information
- Monitor completion status

### **4. Change Log and Audit Trail**
- Complete change tracking for all prescriptions
- Before/after value comparison
- User attribution and timestamps
- Detailed modification history

### **5. Procurement Department Integration**
- Automatic dispatch to appropriate departments
- Status updates from procurement systems
- Real-time synchronization

### **6. Real-time Status Updates**
- Dynamic dashboard updates
- Live status changes
- Automatic refresh of data

## 🔧 Setup Instructions

### **1. Database Setup**
```bash
# Create and apply migrations
python manage.py makemigrations Sheduling
python manage.py migrate

# Set up the complete module
python manage.py setup_complete_prescription_module
```

### **2. Create Sample Data (Optional)**
```bash
# Create sample prescription data for testing
python manage.py create_sample_prescription_data --count 20
```

### **3. User Role Assignment**
1. Go to User Management in the admin panel
2. Assign users to appropriate roles:
   - **Doctors**: Assign to `doctor` role
   - **Scheduling Staff**: Assign to `scheduling_staff` role
   - **Pharmacy Staff**: Assign to `ip_pharmacy_staff` role
   - **Procurement Staff**: Assign to `procurement_staff` role

## 📱 How to Use

### **Accessing the Module**
1. Log in to the system
2. Navigate to "Prescription Scheduling" in the main menu
3. The dashboard will show three sections: Draft, Scheduled, Dispatched

### **Managing Draft Prescriptions**
1. **View Draft Prescriptions**: Select the "Draft" tab
2. **Filter by Date**: Use the date filter to view specific dates
3. **Send Final Prescriptions**: Click "Send Final Prescription" button
4. **View Details**: Click "View Details" to see prescription items

### **Tracking Scheduled Prescriptions**
1. **View Scheduled**: Select the "Scheduled" tab
2. **Monitor Status**: See which department is handling each prescription
3. **Track Progress**: Monitor dispatch status and timestamps

### **Viewing Dispatched Prescriptions**
1. **View Dispatched**: Select the "Dispatched" tab
2. **Monitor Completion**: See all completed prescriptions
3. **View History**: Access complete dispatch history

### **Change Log Management**
1. **View Change Log**: Click "Change Log" button for any prescription
2. **Track Modifications**: See all changes with timestamps
3. **User Attribution**: Know who made each change

## 🔐 Security Features

### **Role-Based Access Control**
- Different access levels for different roles
- Module-level permissions
- API endpoint protection

### **Audit Trail**
- Complete change tracking
- User attribution
- Timestamp logging
- Before/after value comparison

### **Data Validation**
- Input validation on all endpoints
- Error handling and logging
- Transaction safety

## 🔌 API Endpoints

### **Available Endpoints**
- `GET /prescription/api/prescription-data/` - Fetch prescription data
- `GET /prescription/api/prescription-details/` - Get detailed prescription info
- `POST /prescription/api/send-final-prescription/` - Send final prescriptions
- `GET /prescription/api/change-log/` - Get change history
- `POST /prescription/api/update-status/` - Update prescription status

### **API Usage**
```javascript
// Fetch prescription data
fetch('/prescription/api/prescription-data/?status=draft&date=2025-01-15')
  .then(response => response.json())
  .then(data => console.log(data));

// Send final prescription
fetch('/prescription/api/send-final-prescription/', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({date: '2025-01-15'})
});
```

## 📊 Dashboard Features

### **Statistics Display**
- Draft Prescriptions count
- Scheduled Prescriptions count
- Dispatched Prescriptions count

### **Filtering Options**
- Date-based filtering for each section
- Real-time data updates
- Responsive design for all devices

### **Modal Dialogs**
- Prescription details view
- Change log display
- Confirmation dialogs

## 🎯 Best Practices

### **For Doctors**
1. Create prescriptions with complete details
2. Review before sending to procurement
3. Monitor status updates regularly

### **For Scheduling Staff**
1. Review draft prescriptions daily
2. Send final prescriptions to appropriate departments
3. Monitor dispatch status

### **For Procurement Staff**
1. Update prescription status promptly
2. Mark items as dispatched when ready
3. Communicate any issues immediately

### **For Administrators**
1. Monitor system usage and performance
2. Review change logs regularly
3. Ensure proper role assignments

## 🚨 Troubleshooting

### **Common Issues**

#### **Module Not Visible**
- Check user role assignments
- Verify module is active
- Check user permissions

#### **Data Not Loading**
- Check database connections
- Verify API endpoints
- Check user authentication

#### **Permissions Denied**
- Verify role assignments
- Check module permissions
- Contact administrator

### **Support Steps**
1. Check Django logs for errors
2. Verify database connections
3. Check user permissions and roles
4. Review API endpoint responses

## 📈 Future Enhancements

### **Planned Features**
- Real-time notifications
- Advanced reporting
- Mobile app support
- Integration with external systems

### **Customization Options**
- Custom status workflows
- Department-specific configurations
- Advanced filtering options
- Custom reporting

## 🎉 Success Metrics

### **Key Performance Indicators**
- Prescription processing time
- Dispatch accuracy
- User satisfaction
- System reliability

### **Monitoring**
- Track prescription lifecycle
- Monitor user activity
- Measure system performance
- Generate usage reports

---

## 📞 Support

For technical support or questions about the Prescription Scheduling Module:
1. Check the system logs
2. Review user permissions
3. Contact the system administrator
4. Refer to the API documentation

**Module Status**: ✅ Active and Ready for Use
**Last Updated**: January 2025
**Version**: 1.0.0
